"""
Sanal Aracı Kurum ve Emir Yönetim Modülü (Paper Broker).

Bu modül;
- Sanal 1.000.000 TL portföy bütçesini,
- Canlı piyasadan gelen emirlerin komisyon (0.0004) ve kayma (0.0005) düşülerek gerçekleştirilmesini,
- Takasbank teminat kuralına göre serbest teminat (free_margin) ve net varlık değerinin (NAV)
  güncellenmesini yönetir.
"""

from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
from src.core.config import SystemConfig
from src.strategy.position_manager import PositionState

logger = logging.getLogger(__name__)


@dataclass
class PaperTradeExecution:
    """Sanal Gerçekleşen Emir Dekontu."""
    trade_id: int
    symbol: str
    action: str                    # 'OPEN_LONG', 'CLOSE_LONG', 'SCALE_OUT_LONG', vb.
    lots: int
    nominal_price: float
    execution_price: float         # Slippage dahil
    contract_multiplier: float
    notional_value_try: float
    commission_try: float
    slippage_try: float
    realized_pnl_try: float
    timestamp: datetime
    rationale: str


class PaperBroker:
    """
    VİOP Sanal Aracı Kurum Simülatörü.
    """

    COMMISSION_RATE = 0.0004       # On binde 4 komisyon
    SLIPPAGE_RATE = 0.0005         # On binde 5 piyasa emri kayması

    def __init__(
        self,
        initial_capital: float = 2_000_000.0,
        config: Optional[SystemConfig] = None
    ) -> None:
        self.initial_capital = initial_capital
        self.cash_balance = initial_capital
        self.config = config or SystemConfig()

        self.open_positions: Dict[str, PositionState] = {}
        self.market_prices: Dict[str, float] = {}
        self.trade_history: List[PaperTradeExecution] = []
        self._trade_counter = 0

    def update_market_price(self, symbol: str, price: float) -> None:
        """Piyasa fiyatını günceller (Mark-to-Market değerleme için)."""
        if price > 0:
            self.market_prices[symbol] = price

    @property
    def current_nav(self) -> float:
        """Portföyün güncel Net Varlık Değeri (NAV = Nakit + Gerçekleşmemiş PnL)."""
        unrealized = sum(self._get_position_unrealized_pnl(pos) for pos in self.open_positions.values())
        return self.cash_balance + unrealized

    @property
    def total_required_margin(self) -> float:
        """Açık pozisyonların toplam bağlı başlangıç teminatı."""
        total = 0.0
        for pos in self.open_positions.values():
            spec = self.config.contracts.get(pos.symbol)
            im_per_contract = spec.initial_margin_try if spec else 6500.0
            total += abs(pos.lots) * im_per_contract
        return total

    @property
    def free_margin(self) -> float:
        """Serbest Teminat (Free Margin = NAV - Bağlı Başlangıç Teminatı)."""
        return max(0.0, self.current_nav - self.total_required_margin)

    def _get_position_unrealized_pnl(self, pos: PositionState) -> float:
        """Pozisyonun güncel piyasa fiyatı üzerinden gerçekleşmemiş kâr/zararını döner (Mark-to-Market)."""
        if not pos.is_active:
            return 0.0
        spec = self.config.contracts.get(pos.symbol)
        mult = spec.multiplier if spec else 100.0
        curr_p = self.market_prices.get(pos.symbol, pos.entry_price)
        if pos.lots > 0:
            return (curr_p - pos.entry_price) * pos.lots * mult
        else:
            return (pos.entry_price - curr_p) * abs(pos.lots) * mult

    def execute_virtual_order(self, order_details: Dict[str, Any]) -> PaperTradeExecution:
        """
        Gelen teknik emri sanal portföye yansıtır.
        
        Parametreler (order_details):
        - symbol: 'F_THYAO'
        - action: 'ENTER_LONG', 'ENTER_SHORT', 'SCALE_OUT_33', 'SCALE_OUT_50',
                  'PYRAMID_ADD_33', 'TIME_STOP_EXIT', 'CHANDELIER_STOP_EXIT',
                  'TREND_REVERSAL_EXIT', 'FRIDAY_CLOSE_EXIT'
        - lots: int
        - current_price: float
        - stop_price: float
        - rationale: str
        """
        symbol = order_details["symbol"]
        action = order_details["action"]
        target_lots = int(order_details["lots"])
        current_price = float(order_details["current_price"])
        stop_price = float(order_details.get("stop_price", current_price))
        rationale = order_details.get("rationale", "")
        now = order_details.get("timestamp", datetime.utcnow())

        self.market_prices[symbol] = current_price
        spec = self.config.contracts.get(symbol)
        mult = spec.multiplier if spec else 100.0

        self._trade_counter += 1
        realized_pnl = 0.0
        exec_price = current_price
        notional = 0.0
        comm = 0.0
        slip = 0.0

        # =====================================================================
        # 1. YENİ LONG POZİSYON AÇILIŞI
        # =====================================================================
        if action in ("ENTER_LONG", "ENTER_LONG_B_TYPE", "ENTER_LONG_A_TYPE", "ENTER_BREAKAWAY_GAP"):
            exec_price = round(current_price * (1.0 + self.SLIPPAGE_RATE), 2)
            notional = exec_price * target_lots * mult
            comm = notional * self.COMMISSION_RATE
            slip = abs(exec_price - current_price) * target_lots * mult

            self.cash_balance -= comm

            new_pos = PositionState(
                symbol=symbol,
                entry_price=exec_price,
                initial_stop=stop_price,
                trailing_stop=stop_price,
                lots=target_lots,
                entry_time=now,
                r_unit_price=abs(exec_price - stop_price),
                entry_commission_paid=comm
            )
            self.open_positions[symbol] = new_pos

        # =====================================================================
        # 2. YENİ SHORT POZİSYON AÇILIŞI
        # =====================================================================
        elif action in ("ENTER_SHORT", "ENTER_SHORT_B_TYPE", "ENTER_SHORT_A_TYPE"):
            exec_price = round(current_price * (1.0 - self.SLIPPAGE_RATE), 2)
            notional = exec_price * target_lots * mult
            comm = notional * self.COMMISSION_RATE
            slip = abs(current_price - exec_price) * target_lots * mult

            self.cash_balance -= comm

            new_pos = PositionState(
                symbol=symbol,
                entry_price=exec_price,
                initial_stop=stop_price,
                trailing_stop=stop_price,
                lots=-target_lots,
                entry_time=now,
                r_unit_price=abs(stop_price - exec_price),
                entry_commission_paid=comm
            )
            self.open_positions[symbol] = new_pos

        # =====================================================================
        # 3. BEDAVA PİRAMİTLEME (PYRAMID_ADD_33)
        # =====================================================================
        elif action == "PYRAMID_ADD_33" and symbol in self.open_positions:
            pos = self.open_positions[symbol]
            if pos.lots > 0:
                exec_price = round(current_price * (1.0 + self.SLIPPAGE_RATE), 2)
            else:
                exec_price = round(current_price * (1.0 - self.SLIPPAGE_RATE), 2)

            notional = exec_price * target_lots * mult
            comm = notional * self.COMMISSION_RATE
            slip = abs(exec_price - current_price) * target_lots * mult

            self.cash_balance -= comm
            pos.add_pyramid(target_lots)
            pos.entry_commission_paid += comm

        # =====================================================================
        # 4. KISMİ KAPATMA (SCALE-OUT %33 / %50)
        # =====================================================================
        elif action in ("SCALE_OUT_33", "SCALE_OUT_50") and symbol in self.open_positions:
            pos = self.open_positions[symbol]
            is_long = pos.lots > 0
            closed_lots = min(abs(pos.lots), target_lots)

            if is_long:
                exec_price = round(current_price * (1.0 - self.SLIPPAGE_RATE), 2)
                trade_pnl = (exec_price - pos.entry_price) * closed_lots * mult
                pos.lots -= closed_lots
            else:
                exec_price = round(current_price * (1.0 + self.SLIPPAGE_RATE), 2)
                trade_pnl = (pos.entry_price - exec_price) * closed_lots * mult
                pos.lots += closed_lots

            notional = exec_price * closed_lots * mult
            comm = notional * self.COMMISSION_RATE
            slip = abs(exec_price - current_price) * closed_lots * mult

            realized_pnl = trade_pnl - comm
            self.cash_balance += (trade_pnl - comm)
            pos.scaled_out = True
            if stop_price > 0:
                pos.trailing_stop = stop_price

        # =====================================================================
        # 5. TAM KAPATMA (STOP EXIT, CHANDELIER, TREND REVERSAL, FRIDAY CLOSE)
        # =====================================================================
        elif action in (
            "TIME_STOP_EXIT",
            "CHANDELIER_STOP_EXIT",
            "TREND_REVERSAL_EXIT",
            "FRIDAY_CLOSE_EXIT"
        ) and symbol in self.open_positions:
            pos = self.open_positions[symbol]
            closing_lots = abs(pos.lots)
            is_long = pos.lots > 0

            if is_long:
                exec_price = round(current_price * (1.0 - self.SLIPPAGE_RATE), 2)
                trade_pnl = (exec_price - pos.entry_price) * closing_lots * mult
            else:
                exec_price = round(current_price * (1.0 + self.SLIPPAGE_RATE), 2)
                trade_pnl = (pos.entry_price - exec_price) * closing_lots * mult

            notional = exec_price * closing_lots * mult
            comm = notional * self.COMMISSION_RATE
            slip = abs(exec_price - current_price) * closing_lots * mult

            realized_pnl = trade_pnl - comm
            self.cash_balance += (trade_pnl - comm)
            del self.open_positions[symbol]

        trade_record = PaperTradeExecution(
            trade_id=self._trade_counter,
            symbol=symbol,
            action=action,
            lots=target_lots,
            nominal_price=current_price,
            execution_price=exec_price,
            contract_multiplier=mult,
            notional_value_try=round(notional, 2),
            commission_try=round(comm, 2),
            slippage_try=round(slip, 2),
            realized_pnl_try=round(realized_pnl, 2),
            timestamp=now,
            rationale=rationale
        )
        self.trade_history.append(trade_record)
        return trade_record
