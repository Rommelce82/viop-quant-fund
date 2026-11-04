"""
Akıllı Emir Yönlendirme ve Çoklu Broker Motoru (Smart Order Router - SOR).

Bu modül;
- Birden fazla aracı kurum gateway'ini (FixBrokerGateway, RestApiBrokerGateway vb.) koordine eder.
- Gün içi serbest teminat (free margin) ve komisyon oranlarına göre en optimum rotayı seçer.
- Büyük hacimli kurumsal emirleri (>1.000 kontrat) piyasa etkisini (market impact) minimize
  etmek amacıyla Iceberg/TWAP dilimlerine (slices) bölerek çoklu kuruma dağıtır.
- Anlık bağlantı kopması (disconnect) durumunda Cancel-on-Disconnect (CoD) varsayıp
  kalan lotları yedek aracı kuruma kesintisiz aktarır (Failover & Reconciliation).
"""

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Dict, List, Optional, Tuple
import uuid

from src.execution.broker_gateway import (
    AbstractBrokerGateway,
    OrderAction,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger(__name__)


@dataclass
class ConsolidatedExecutionSummary:
    """Çoklu Broker Üzerinden İcra Edilen Konsolide Emir Özeti."""
    parent_order_id: str
    symbol: str
    action: OrderAction
    requested_lots: int
    executed_lots: int
    remaining_lots: int
    vwap_price: float
    total_commission_try: float
    broker_allocations: Dict[str, int]
    child_executions: List[OrderResult]
    failovers_occurred: int
    is_fully_executed: bool
    status: OrderStatus
    timestamp: datetime


class SmartOrderRouter:
    """
    VİOP Çoklu Aracı Kurum ve Akıllı Emir Dağıtım Motoru (SOR).
    """

    def __init__(
        self,
        gateways: Optional[List[AbstractBrokerGateway]] = None,
        large_order_threshold: int = 1000,
        iceberg_slice_size: int = 250,
        margin_per_contract: float = 7000.0
    ) -> None:
        self.gateways: List[AbstractBrokerGateway] = gateways or []
        self.large_order_threshold = large_order_threshold
        self.iceberg_slice_size = iceberg_slice_size
        self.margin_per_contract = margin_per_contract
        self.execution_history: List[ConsolidatedExecutionSummary] = []

    def register_gateway(self, gateway: AbstractBrokerGateway) -> None:
        """Yeni bir aracı kurum gateway'i ekler."""
        if not any(g.broker_id == gateway.broker_id for g in self.gateways):
            self.gateways.append(gateway)
            logger.info(f"Gateway kaydedildi: {gateway.name} ({gateway.broker_id}) [{gateway.protocol}]")

    def get_connected_gateways(self) -> List[AbstractBrokerGateway]:
        """Aktif ve bağlı durumda olan gateway'leri döner."""
        return [g for g in self.gateways if g.is_connected]

    def get_consolidated_free_margin(self) -> float:
        """Tüm bağlı aracı kurumlardaki toplam serbest teminatı döner."""
        return sum(g.get_free_margin() for g in self.get_connected_gateways())

    def route_order(
        self,
        symbol: str,
        action: OrderAction,
        lots: int,
        price: float,
        order_type: OrderType = OrderType.LIMIT,
        prefer_lowest_commission: bool = True
    ) -> ConsolidatedExecutionSummary:
        """
        Emri en uygun aracı kurumlara yönlendirir, gerekirse dilimler (Iceberg)
        ve kopma durumunda yedek broker'a devreder (Failover).
        """
        parent_id = f"PARENT_{uuid.uuid4().hex[:8].upper()}"
        active_gateways = self.get_connected_gateways()

        if not active_gateways:
            # Hiç aktif broker yok
            summary = ConsolidatedExecutionSummary(
                parent_order_id=parent_id,
                symbol=symbol,
                action=action,
                requested_lots=lots,
                executed_lots=0,
                remaining_lots=lots,
                vwap_price=0.0,
                total_commission_try=0.0,
                broker_allocations={},
                child_executions=[],
                failovers_occurred=0,
                is_fully_executed=False,
                status=OrderStatus.REJECTED,
                timestamp=datetime.now()
            )
            self.execution_history.append(summary)
            return summary

        # Komisyon önceliğine göre sırala (Düşük komisyon -> Yüksek komisyon)
        if prefer_lowest_commission:
            sorted_gateways = sorted(active_gateways, key=lambda g: g.commission_rate)
        else:
            sorted_gateways = sorted(active_gateways, key=lambda g: g.get_free_margin(), reverse=True)

        # 1. Aşama: Büyük Emir ve Algoritmik Dilimleme (Iceberg / TWAP)
        slices: List[int] = []
        if lots > self.large_order_threshold:
            remaining = lots
            while remaining > 0:
                chunk = min(remaining, self.iceberg_slice_size)
                slices.append(chunk)
                remaining -= chunk
        else:
            slices = [lots]

        child_results: List[OrderResult] = []
        allocations: Dict[str, int] = {}
        failover_count = 0
        total_executed = 0
        total_cost_volume = 0.0
        total_commission = 0.0

        # 2. Aşama: Dilimlerin Dağıtımı ve İcrası
        for slice_lots in slices:
            unfilled_in_slice = slice_lots

            for gateway in sorted_gateways:
                if unfilled_in_slice <= 0:
                    break

                if not gateway.is_connected:
                    continue

                free_margin = gateway.get_free_margin()
                max_lots_by_margin = int(free_margin // self.margin_per_contract)
                if max_lots_by_margin <= 0:
                    continue

                lots_to_send = min(unfilled_in_slice, max_lots_by_margin)
                child_req = OrderRequest(
                    symbol=symbol,
                    action=action,
                    order_type=order_type,
                    lots=lots_to_send,
                    price=price,
                    notes=f"Parent: {parent_id} | Slice of {slice_lots}"
                )

                try:
                    result = gateway.send_order(child_req)
                    child_results.append(result)

                    if result.status == OrderStatus.FILLED:
                        unfilled_in_slice -= result.executed_lots
                        total_executed += result.executed_lots
                        total_cost_volume += (result.executed_lots * result.execution_price)
                        total_commission += result.commission_try
                        allocations[gateway.broker_id] = allocations.get(gateway.broker_id, 0) + result.executed_lots
                    elif result.status == OrderStatus.REJECTED:
                        # Reddedildi - Temiz failover
                        failover_count += 1
                        logger.warning(
                            f"Gateway {gateway.broker_id} emri reddetti: {result.message}. "
                            f"Yedek gateway'e geçiliyor."
                        )
                    elif result.status == OrderStatus.PENDING:
                        # Beklemede kaldı - Çift işlem riskini önlemek için önce iptal mutabakatı yap
                        logger.warning(
                            f"Gateway {gateway.broker_id} emir beklemede kaldı! "
                            f"Çift gönderimi önlemek için iptal edilip failover yapılıyor."
                        )
                        try:
                            gateway.cancel_order(child_req.order_id)
                        except Exception as cancel_err:
                            logger.error(f"Gateway {gateway.broker_id} iptal mutabakatı hatası: {cancel_err}")
                        failover_count += 1
                except Exception as e:
                    # Gateway çöktü / timeout - Çift gönderim riskini önlemek için durum teyidi / iptal dene
                    failover_count += 1
                    logger.error(f"Gateway {gateway.broker_id} iletişim hatası: {e}. Failover öncesi iptal mutabakatı deneniyor.")
                    try:
                        gateway.cancel_order(child_req.order_id)
                    except Exception as cancel_err:
                        logger.warning(f"Gateway {gateway.broker_id} iptal mutabakatı yanıt vermedi: {cancel_err}")

            # Eğer tüm gateway'ler dolaşıldı ve hala dolmayan varsa
            if unfilled_in_slice > 0:
                logger.warning(f"Dilim tam karşılanamadı, {unfilled_in_slice} lot açıkta kaldı.")

        vwap = (total_cost_volume / total_executed) if total_executed > 0 else 0.0
        is_full = (total_executed == lots)
        status = OrderStatus.FILLED if is_full else (OrderStatus.PARTIALLY_FILLED if total_executed > 0 else OrderStatus.REJECTED)

        summary = ConsolidatedExecutionSummary(
            parent_order_id=parent_id,
            symbol=symbol,
            action=action,
            requested_lots=lots,
            executed_lots=total_executed,
            remaining_lots=lots - total_executed,
            vwap_price=round(vwap, 2),
            total_commission_try=round(total_commission, 2),
            broker_allocations=allocations,
            child_executions=child_results,
            failovers_occurred=failover_count,
            is_fully_executed=is_full,
            status=status,
            timestamp=datetime.now()
        )
        self.execution_history.append(summary)
        return summary
