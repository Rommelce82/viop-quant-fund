"""
VİOP Fiyat Kayması (Slippage) ve Piyasa Etkisi Modeli.

Bu modül;
- Emir büyüklüğü / bar hacmi oranı,
- Spread (Alış-Satış farkı),
- Piyasa Rejimi (Volatilite) faktörlerini birleştirerek
gerçekçi emir dolum fiyatını hesaplar.
"""

from src.core.models import MarketBar, MarketRegime, OrderSide


class ViopSlippageModel:
    """
    Likidite ve Spread Duyarlı VİOP Kayma Modeli.
    """

    def __init__(self, base_spread_bps: float = 2.0) -> None:
        """
        Args:
            base_spread_bps: Normal piyasa koşullarındaki baz spread (Bps = Yüzde baz puan).
        """
        self.base_spread_bps = base_spread_bps

    def calculate_fill_price(
        self,
        nominal_price: float,
        side: OrderSide,
        contracts: int,
        current_bar: MarketBar,
        regime: MarketRegime,
        tick_size: float = 0.25
    ) -> float:
        """
        Kayma ve spread maliyetini ekleyerek fiili gerçekleşme fiyatını belirler.
        """
        # 1. Spread Maliyeti (Baz puan cinsinden)
        spread_bps = self.base_spread_bps
        if regime == MarketRegime.HIGH_VOLATILITY:
            spread_bps *= 2.5  # Volatil dönemde makas 2.5 katına açılır

        half_spread_pct = (spread_bps / 10_000.0) / 2.0
        spread_impact = nominal_price * half_spread_pct

        # 2. Likidite / Piyasa Etkisi (Bar Hacmine Oranla Kayma)
        # Hacmin binde 1'ini geçen emirler ilave kademe kayması yaşar
        order_volume_est = abs(contracts)
        bar_volume = max(100.0, current_bar.volume)
        participation_rate = order_volume_est / bar_volume
        
        # Piyasa etkisi faktörü:
        impact_pct = min(0.005, (participation_rate ** 0.5) * 0.001)
        volume_impact = nominal_price * impact_pct

        total_penalty = spread_impact + volume_impact

        # 3. Yönlü Düzeltme
        if side == OrderSide.BUY:
            raw_fill_price = nominal_price + total_penalty
            # Tick size'a yukarı yuvarla
            fill_price = round(raw_fill_price / tick_size) * tick_size
        else:
            raw_fill_price = nominal_price - total_penalty
            # Tick size'a aşağı yuvarla
            fill_price = round(raw_fill_price / tick_size) * tick_size

        return round(fill_price, 2)
