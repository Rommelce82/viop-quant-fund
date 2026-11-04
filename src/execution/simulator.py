"""
VİOP Olay Güdümlü Yürütme ve Backtest Simülatörü (Execution Simulator).

Bu modül;
- Komisyon ve Borsa paylarını,
- Likidite ve Fiyat kaymasını (Slippage Model),
- Açık pozisyon PnL ve Takasbank teminatlandırmasını,
- Gün İçi / Gün Sonu Kar/Zarar takibini
birebir VİOP piyasa kurallarıyla simüle eder.
"""

from datetime import datetime
from typing import Dict, List, Optional
from src.core.config import SystemConfig
from src.core.models import (
    ConsensusDecision,
    MarketBar,
    Order,
    OrderSide,
    OrderType,
    Position,
    SignalType
)
from src.execution.slippage_model import ViopSlippageModel
from src.risk.stop_manager import TrailingStopManager
from src.risk.viop_margin import ViopMarginManager


class ExecutionSimulator:
    """
    VİOP Gerçekçi Emir Gerçekleştirme ve Portföy Yönetim Motoru.
    """

    def __init__(
        self,
        config: SystemConfig,
        margin_manager: ViopMarginManager,
        slippage_model: ViopSlippageModel,
        stop_manager: TrailingStopManager
    ) -> None:
        """
        Simülatörü ilklendirir.
        """
        self.config = config
        self.margin_manager = margin_manager
        self.slippage = slippage_model
        self.stop_manager = stop_manager

        self.cash_balance: float = config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Dict] = []

    def get_position(self, symbol: str) -> Position:
        """Sembolün mevcut pozisyonunu döner veya 0 adetli yeni nesne ilklendirir."""
        if symbol not in self.positions:
            spec = self.config.contracts[symbol]
            self.positions[symbol] = Position(
                symbol=symbol,
                quantity=0,
                average_entry_price=0.0,
                current_price=0.0,
                contract_multiplier=spec.multiplier,
                initial_margin_per_contract=spec.initial_margin_try,
                trailing_stop_price=None
            )
        return self.positions[symbol]

    def on_market_bar(self, bar: MarketBar) -> None:
        """
        Her yeni bar geldiğinde açık pozisyonun fiyatını günceller ve iz süren stop kontrolü yapar.
        """
        pos = self.get_position(bar.symbol)
        pos.current_price = bar.close

        if pos.quantity != 0:
            # İz süren stop tetiklendi mi?
            if self.stop_manager.is_stop_triggered(pos, bar):
                # Stop tetiklendi, pozisyonu kapat
                self._close_position_by_stop(pos, bar)

    def _close_position_by_stop(self, pos: Position, bar: MarketBar) -> None:
        """Stop tetiklenmesi durumunda piyasa emriyle pozisyonu tasfiye eder."""
        side = OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY
        closing_contracts = abs(pos.quantity)
        exit_price = pos.trailing_stop_price or bar.close

        self.execute_order(
            Order(
                order_id=f"STOP_{pos.symbol}_{bar.timestamp.strftime('%H%M%S')}",
                symbol=pos.symbol,
                side=side,
                quantity=closing_contracts,
                order_type=OrderType.STOP_MARKET,
                limit_price=exit_price,
                created_at=bar.timestamp
            ),
            current_bar=bar,
            regime_val="HIGH_VOLATILITY"
        )
        pos.trailing_stop_price = None

    def execute_order(
        self,
        order: Order,
        current_bar: MarketBar,
        regime_val: str = "BULL_TREND"
    ) -> Dict:
        """
        Emri kayma (slippage) ve komisyon düşerek gerçekleştirir.
        """
        spec = self.config.contracts[order.symbol]
        pos = self.get_position(order.symbol)

        # 1. Kaymalı Dolum Fiyatı Hesabı
        fill_price = self.slippage.calculate_fill_price(
            nominal_price=current_bar.close,
            side=order.side,
            contracts=order.quantity,
            current_bar=current_bar,
            regime=getattr(current_bar, "regime", None) or "BULL_TREND",
            tick_size=spec.tick_size
        )

        # 2. Komisyon Tutarı = Sözleşme Adedi * Fiyat * Çarpan * Komisyon Oranı
        notional_traded = order.quantity * fill_price * spec.multiplier
        commission = notional_traded * spec.commission_rate
        self.cash_balance -= commission

        signed_contracts = order.quantity if order.side == OrderSide.BUY else -order.quantity

        # 3. Pozisyon Defteri Güncellemesi
        realized_pnl = 0.0

        if pos.quantity == 0:
            # Sıfırdan pozisyon açılışı
            pos.quantity = signed_contracts
            pos.average_entry_price = fill_price
            pos.current_price = fill_price

        elif (pos.quantity > 0 and signed_contracts > 0) or (pos.quantity < 0 and signed_contracts < 0):
            # Mevcut pozisyonu artırma (Averaging)
            new_total_qty = pos.quantity + signed_contracts
            total_cost = (abs(pos.quantity) * pos.average_entry_price) + (abs(signed_contracts) * fill_price)
            pos.average_entry_price = total_cost / abs(new_total_qty)
            pos.quantity = new_total_qty
            pos.current_price = fill_price

        else:
            # Pozisyon azaltma veya tersine dönme (Kısmi/Tam Kapatma)
            closed_qty = min(abs(pos.quantity), abs(signed_contracts))
            direction = 1 if pos.quantity > 0 else -1

            realized_pnl = closed_qty * (fill_price - pos.average_entry_price) * direction * spec.multiplier
            self.cash_balance += realized_pnl

            remaining_qty = pos.quantity + signed_contracts
            if remaining_qty == 0:
                pos.quantity = 0
                pos.average_entry_price = 0.0
            elif (direction > 0 and remaining_qty < 0) or (direction < 0 and remaining_qty > 0):
                # Ters pozisyona geçildi
                pos.quantity = remaining_qty
                pos.average_entry_price = fill_price
            else:
                pos.quantity = remaining_qty

            pos.current_price = fill_price

        trade_record = {
            "order_id": order.order_id,
            "timestamp": order.created_at,
            "symbol": order.symbol,
            "side": order.side.value,
            "contracts": order.quantity,
            "fill_price": fill_price,
            "commission": commission,
            "realized_pnl": realized_pnl,
            "cash_balance": self.cash_balance
        }
        self.trade_history.append(trade_record)
        return trade_record
