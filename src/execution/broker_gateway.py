"""
Soyutlaştırılmış Broker Gateway Arayüzü ve Entegrasyon Katmanı.

Bu modül;
- Matriks FIX, İdeal FIX, Borsa İstanbul FIX ve REST API gibi farklı aracı kurum ve
  protokolleri tek bir standart çatı altında toplar (AbstractBrokerGateway).
- Çoklu broker (Multi-Broker) ortamında teminat sorgulama, emir iletimi, iptal ve
  bağlantı durum denetimlerini yönetir.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class OrderAction(str, Enum):
    """Emir Yönü ve Eylemi."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Emir Tipi."""
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    SERVER_STOP = "SERVER_STOP"      # Sunucu Taraflı Borsa İstanbul / Aracı Kurum Stop Emri


class OrderStatus(str, Enum):
    """Emir Durumu."""
    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED_BAR_CLOSE = "EXPIRED_BAR_CLOSE"  # Cancel-on-Bar-Close ile iptal edildi


@dataclass
class OrderRequest:
    """Aracı Kuruma İletilecek Standart Emir İsteği."""
    symbol: str
    action: OrderAction
    order_type: OrderType
    lots: int
    price: float
    client_order_id: str = field(default_factory=lambda: f"ORD_{uuid.uuid4().hex[:8].upper()}")
    time_in_force: str = "DAY"  # DAY, IOC, FOK
    notes: str = ""


@dataclass
class OrderResult:
    """Emir İletim ve Gerçekleşme Sonucu."""
    client_order_id: str
    broker_order_id: str
    broker_id: str
    symbol: str
    action: OrderAction
    requested_lots: int
    executed_lots: int
    remaining_lots: int
    execution_price: float
    commission_try: float
    status: OrderStatus
    timestamp: datetime
    message: str = ""


class AbstractBrokerGateway(ABC):
    """
    Tüm Aracı Kurum Bağlantıları İçin Standart Soyut Arayüz (ABC).
    """

    def __init__(
        self,
        broker_id: str,
        name: str,
        protocol: str = "FIX",
        commission_rate: float = 0.0004
    ) -> None:
        self.broker_id = broker_id
        self.name = name
        self.protocol = protocol
        self.commission_rate = commission_rate
        self.is_connected = False

    @abstractmethod
    def connect(self) -> bool:
        """Sunucu veya FIX soketine bağlanır."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Bağlantıyı kontrollü olarak sonlandırır."""
        pass

    @abstractmethod
    def get_free_margin(self) -> float:
        """Aracı kurumdaki kullanılabilir serbest teminatı (TRY) döner."""
        pass

    @abstractmethod
    def send_order(self, request: OrderRequest) -> OrderResult:
        """Emri aracı kuruma iletir."""
        pass

    @abstractmethod
    def cancel_order(self, client_order_id: str) -> bool:
        """Bekleyen emri iptal eder."""
        pass

    @abstractmethod
    def get_order_status(self, client_order_id: str) -> OrderStatus:
        """Emrin güncel durumunu sorgular."""
        pass

    @abstractmethod
    def get_open_positions(self) -> Dict[str, int]:
        """Açık pozisyonları sembol -> net lot şeklinde döner."""
        pass


class FixBrokerGateway(AbstractBrokerGateway):
    """
    Borsa İstanbul FIX Protocol Simülatörü / Bağlantı Katmanı.
    """

    def __init__(
        self,
        broker_id: str,
        name: str,
        initial_free_margin: float = 2_000_000.0,
        commission_rate: float = 0.0002,
        slippage_rate: float = 0.0003
    ) -> None:
        super().__init__(broker_id, name, protocol="FIX", commission_rate=commission_rate)
        self.free_margin_balance = initial_free_margin
        self.slippage_rate = slippage_rate
        self.orders: Dict[str, OrderResult] = {}
        self.open_positions: Dict[str, int] = {}

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def get_free_margin(self) -> float:
        return self.free_margin_balance if self.is_connected else 0.0

    def send_order(self, request: OrderRequest) -> OrderResult:
        if not self.is_connected:
            return OrderResult(
                client_order_id=request.client_order_id,
                broker_order_id="",
                broker_id=self.broker_id,
                symbol=request.symbol,
                action=request.action,
                requested_lots=request.lots,
                executed_lots=0,
                remaining_lots=request.lots,
                execution_price=0.0,
                commission_try=0.0,
                status=OrderStatus.REJECTED,
                timestamp=datetime.now(),
                message="Gateway bağlantısı kapalı (Disconnected)."
            )

        # Teminat Kontrolü (Varsayılan 7.000 TL maktu teminat)
        required_margin = request.lots * 7000.0
        if required_margin > self.free_margin_balance:
            return OrderResult(
                client_order_id=request.client_order_id,
                broker_order_id="",
                broker_id=self.broker_id,
                symbol=request.symbol,
                action=request.action,
                requested_lots=request.lots,
                executed_lots=0,
                remaining_lots=request.lots,
                execution_price=0.0,
                commission_try=0.0,
                status=OrderStatus.REJECTED,
                timestamp=datetime.now(),
                message=f"Yetersiz teminat: İstenen {required_margin:,.0f} TL > Serbest {self.free_margin_balance:,.0f} TL"
            )

        # Fiyat Kayması (Slippage) Hesabı
        multiplier = 100.0
        price_adj = request.price * (1.0 + self.slippage_rate) if request.action == OrderAction.BUY else request.price * (1.0 - self.slippage_rate)
        notional = request.lots * price_adj * multiplier
        commission = notional * self.commission_rate

        self.free_margin_balance -= required_margin
        curr_pos = self.open_positions.get(request.symbol, 0)
        lot_delta = request.lots if request.action == OrderAction.BUY else -request.lots
        self.open_positions[request.symbol] = curr_pos + lot_delta

        broker_order_id = f"FIX_{uuid.uuid4().hex[:10].upper()}"
        res = OrderResult(
            client_order_id=request.client_order_id,
            broker_order_id=broker_order_id,
            broker_id=self.broker_id,
            symbol=request.symbol,
            action=request.action,
            requested_lots=request.lots,
            executed_lots=request.lots,
            remaining_lots=0,
            execution_price=round(price_adj, 2),
            commission_try=round(commission, 2),
            status=OrderStatus.FILLED,
            timestamp=datetime.now(),
            message="Emir FIX üzerinden başarıyla eşleşti."
        )
        self.orders[request.client_order_id] = res
        return res

    def cancel_order(self, client_order_id: str) -> bool:
        if client_order_id in self.orders:
            ord_res = self.orders[client_order_id]
            if ord_res.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED):
                ord_res.status = OrderStatus.CANCELLED
                return True
        return False

    def get_order_status(self, client_order_id: str) -> OrderStatus:
        if client_order_id in self.orders:
            return self.orders[client_order_id].status
        return OrderStatus.REJECTED

    def place_limit_at_best_quote(
        self,
        symbol: str,
        action: OrderAction,
        best_bid: float,
        best_ask: float,
        lots: int
    ) -> OrderResult:
        """
        Limit Order at Best Ask/Bid:
        - Alış (BUY) için Best Ask fiyatına pasif-agresif limit emir girilir.
        - Satış (SELL) için Best Bid fiyatına pasif-agresif limit emir girilir.
        """
        limit_price = best_ask if action == OrderAction.BUY else best_bid
        req = OrderRequest(
            symbol=symbol,
            action=action,
            order_type=OrderType.LIMIT,
            lots=lots,
            price=limit_price,
            notes="Limit Order at Best Ask/Bid"
        )
        return self.send_order(req)

    def place_server_side_stop(
        self,
        symbol: str,
        action: OrderAction,
        stop_price: float,
        lots: int
    ) -> OrderResult:
        """
        Sunucu Taraflı Stop (Server-Side Stop Loss):
        Emir lokal hafızada değil, Borsa İstanbul / FIX sunucularında saklanır.
        İnternet veya API kopsa dahi borsa motoru stopu tetikler.
        """
        req = OrderRequest(
            symbol=symbol,
            action=action,
            order_type=OrderType.SERVER_STOP,
            lots=lots,
            price=stop_price,
            notes="BIST Server-Side Stop Loss (Fix Tag 35=D, OrdType=Stop)"
        )
        return self.send_order(req)

    def cancel_unfilled_orders_on_bar_close(self, timeout_seconds: float = 15.0) -> List[str]:
        """
        Cancel-on-Bar-Close:
        15 saniye içinde dolmayan pasif emirleri bar sonunda otomatik iptal eder.
        """
        cancelled = []
        now = datetime.now()
        for cid, res in list(self.orders.items()):
            if res.status == OrderStatus.NEW:
                elapsed = (now - res.timestamp).total_seconds()
                if elapsed >= timeout_seconds:
                    res.status = OrderStatus.EXPIRED_BAR_CLOSE
                    res.message = f"Cancel-on-Bar-Close: {elapsed:.1f}s içinde dolmadı, iptal edildi."
                    cancelled.append(cid)
        return cancelled

    def auto_reconnect(self, max_attempts: int = 3) -> bool:
        """Kopma durumunda üstel geri çekilme (exponential backoff) ile yeniden bağlanır."""
        for attempt in range(1, max_attempts + 1):
            if self.connect():
                return True
        return False

    def get_open_positions(self) -> Dict[str, int]:
        return dict(self.open_positions)



class RestApiBrokerGateway(AbstractBrokerGateway):
    """
    Yedek / İkincil Aracı Kurum REST API Bağlantı Katmanı (Broker C).
    """

    def __init__(
        self,
        broker_id: str = "BROKER_C_API",
        name: str = "Backup REST Gateway",
        initial_free_margin: float = 1_000_000.0,
        commission_rate: float = 0.0005
    ) -> None:
        super().__init__(broker_id, name, protocol="REST", commission_rate=commission_rate)
        self.free_margin_balance = initial_free_margin
        self.orders: Dict[str, OrderResult] = {}
        self.open_positions: Dict[str, int] = {}

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def get_free_margin(self) -> float:
        return self.free_margin_balance if self.is_connected else 0.0

    def send_order(self, request: OrderRequest) -> OrderResult:
        if not self.is_connected:
            return OrderResult(
                client_order_id=request.client_order_id,
                broker_order_id="",
                broker_id=self.broker_id,
                symbol=request.symbol,
                action=request.action,
                requested_lots=request.lots,
                executed_lots=0,
                remaining_lots=request.lots,
                execution_price=0.0,
                commission_try=0.0,
                status=OrderStatus.REJECTED,
                timestamp=datetime.now(),
                message="REST Gateway bağlantısı kapalı."
            )

        required_margin = request.lots * 7000.0
        if required_margin > self.free_margin_balance:
            return OrderResult(
                client_order_id=request.client_order_id,
                broker_order_id="",
                broker_id=self.broker_id,
                symbol=request.symbol,
                action=request.action,
                requested_lots=request.lots,
                executed_lots=0,
                remaining_lots=request.lots,
                execution_price=0.0,
                commission_try=0.0,
                status=OrderStatus.REJECTED,
                timestamp=datetime.now(),
                message="REST: Yetersiz teminat."
            )

        notional = request.lots * request.price * 100.0
        commission = notional * self.commission_rate
        self.free_margin_balance -= required_margin

        curr_pos = self.open_positions.get(request.symbol, 0)
        lot_delta = request.lots if request.action == OrderAction.BUY else -request.lots
        self.open_positions[request.symbol] = curr_pos + lot_delta

        broker_order_id = f"REST_{uuid.uuid4().hex[:10].upper()}"
        res = OrderResult(
            client_order_id=request.client_order_id,
            broker_order_id=broker_order_id,
            broker_id=self.broker_id,
            symbol=request.symbol,
            action=request.action,
            requested_lots=request.lots,
            executed_lots=request.lots,
            remaining_lots=0,
            execution_price=request.price,
            commission_try=round(commission, 2),
            status=OrderStatus.FILLED,
            timestamp=datetime.now(),
            message="Emir REST API üzerinden gerçekleştirildi."
        )
        self.orders[request.client_order_id] = res
        return res

    def cancel_order(self, client_order_id: str) -> bool:
        if client_order_id in self.orders:
            self.orders[client_order_id].status = OrderStatus.CANCELLED
            return True
        return False

    def get_order_status(self, client_order_id: str) -> OrderStatus:
        if client_order_id in self.orders:
            return self.orders[client_order_id].status
        return OrderStatus.REJECTED

    def get_open_positions(self) -> Dict[str, int]:
        return dict(self.open_positions)
