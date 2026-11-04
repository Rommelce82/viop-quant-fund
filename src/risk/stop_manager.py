"""
Dinamik İz Süren Stop (Trailing Stop) ve Risk Yöneticisi.

Bu modül;
- ATR tabanlı dinamik stop bantları,
- Karda ilerledikçe başabaş (Breakeven) ve iz süren seviyelerini yukarı/aşağı taşıma,
- Kar realizasyonu (Take Profit) hedeflerini yönetir.
"""

from typing import Optional
from src.core.models import MarketBar, MarketRegime, Position


class TrailingStopManager:
    """
    Volatilite Duyarlı Dinamik İz Süren Stop Yöneticisi.
    """

    def __init__(self, atr_multiplier: float = 2.5) -> None:
        """
        Args:
            atr_multiplier: ATR katsayısı (Rejime göre dinamik esner).
        """
        self.base_atr_multiplier = atr_multiplier

    def get_initial_stop_price(
        self,
        entry_price: float,
        is_long: bool,
        atr: float,
        regime: MarketRegime
    ) -> float:
        """
        Pozisyon açılışındaki ilk stop-loss fiyat seviyesini belirler.
        """
        # Rejime göre ATR katsayısını ayarla (Yüksek volatilitede stopu genişlet)
        mult = self.base_atr_multiplier
        if regime == MarketRegime.HIGH_VOLATILITY:
            mult = self.base_atr_multiplier * 1.5
        elif regime == MarketRegime.RANGING_LOW_VOL:
            mult = self.base_atr_multiplier * 0.8

        stop_distance = atr * mult

        if is_long:
            return round(entry_price - stop_distance, 2)
        else:
            return round(entry_price + stop_distance, 2)

    def update_trailing_stop(
        self,
        position: Position,
        current_bar: MarketBar,
        atr: float,
        regime: MarketRegime
    ) -> Optional[float]:
        """
        Fiyat pozisyon lehine ilerledikçe iz süren stopu günceller (Sadece karlı yöne hareket eder).
        
        Returns:
            Güncellenmiş yeni stop seviyesi.
        """
        is_long = position.quantity > 0
        mult = self.base_atr_multiplier
        if regime == MarketRegime.HIGH_VOLATILITY:
            mult = self.base_atr_multiplier * 1.5

        stop_distance = atr * mult
        current_stop = position.trailing_stop_price

        if is_long:
            # Long pozisyon için stop seviyesi sadece yukarı taşınabilir
            candidate_stop = current_bar.high - stop_distance
            if current_stop is None:
                new_stop = candidate_stop
            else:
                new_stop = max(current_stop, candidate_stop)
        else:
            # Short pozisyon için stop seviyesi sadece aşağı taşınabilir
            candidate_stop = current_bar.low + stop_distance
            if current_stop is None:
                new_stop = candidate_stop
            else:
                new_stop = min(current_stop, candidate_stop)

        position.trailing_stop_price = round(new_stop, 2)
        return position.trailing_stop_price

    def is_stop_triggered(self, position: Position, current_bar: MarketBar) -> bool:
        """Mevcut barın tepe/dip fiyatının stop seviyesini ihlal edip etmediğini kontrol eder."""
        if position.trailing_stop_price is None or position.quantity == 0:
            return False

        if position.quantity > 0:
            # Long pozisyonda Low stop seviyesine veya altına indi mi?
            return current_bar.low <= position.trailing_stop_price
        else:
            # Short pozisyonda High stop seviyesine veya üstüne çıktı mı?
            return current_bar.high >= position.trailing_stop_price
