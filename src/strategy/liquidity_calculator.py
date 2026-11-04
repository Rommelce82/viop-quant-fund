"""
Likidite ve Mikro-Yapı Hesaplama Modülü (UniverseFilter & Liquidity).

Fintables PRO MCP'de anlık L1/L2 (derinlik / alış-satış kademeleri) verisi
bulunmadığında;
1. Amihud İllikidite Endeksi (Amihud Illiquidity Ratio):
   ILLIQ = (1 / N) * SUM(|Return_t| / DollarVolume_t)
2. Corwin-Schultz (2012) Spread Estimator:
   Günlük High ve Low fiyatlarının 2 günlük bileşkesi üzerinden efektif alış-satış
   makasını (Effective Bid-Ask Spread) volatilite ayrıştırmasıyla tahmin eder.
"""

import math
from typing import Dict, List, Tuple


class LiquidityCalculator:
    """
    VİOP ve Hisse Evreni İçin İllikidite ve Efektif Makas Hesaplayıcı.
    """

    @staticmethod
    def calculate_amihud_illiquidity(
        returns: List[float],
        volumes_try: List[float]
    ) -> float:
        """
        Amihud (2002) İllikidite Oranını hesaplar.
        
        Args:
            returns: Günlük mutlak getiri serisi (|r_t|).
            volumes_try: Günlük TL işlem hacmi serisi (TRY Volume).
            
        Returns:
            float: Ortalama Amihud Katsayısı (Düşük değer = Yüksek likidite).
        """
        if not returns or not volumes_try or len(returns) != len(volumes_try):
            return 0.0

        ratios: List[float] = []
        for ret, vol in zip(returns, volumes_try):
            if vol <= 0.0 or math.isnan(vol):
                continue
            # |R_t| / Volume_t (Milyon TL cinsinden normalize edilir)
            vol_millions = vol / 1_000_000.0
            ratios.append(abs(ret) / vol_millions)

        if not ratios:
            return 0.0

        return sum(ratios) / len(ratios)

    @staticmethod
    def calculate_corwin_schultz_spread(
        high_low_pairs: List[Tuple[float, float]]
    ) -> float:
        """
        Corwin-Schultz (2012) High-Low Efektif Alış/Satış Makası Tahmincisi.
        
        L2 derinlik verisi olmadan 2 günlük ardışık tepe ve dip fiyatlarından
        gerçekleşen efektif spread'i ayrıştırır.
        
        Args:
            high_low_pairs: Ardışık 2 günün [(High_1, Low_1), (High_2, Low_2)] değerleri.
            
        Returns:
            float: Tahmini Efektif Spread Oranı (Örn: 0.0025 = %0.25).
        """
        if len(high_low_pairs) < 2:
            return 0.0015  # Varsayılan BIST30 spreadi (~15 bps)

        h1, l1 = high_low_pairs[0]
        h2, l2 = high_low_pairs[1]

        # Fiyat koruması
        if l1 <= 0 or l2 <= 0 or h1 <= l1 or h2 <= l2:
            return 0.0015

        # 1 Günlük log(High/Low)^2 toplamı: Beta
        log_hl_1 = math.log(h1 / l1)
        log_hl_2 = math.log(h2 / l2)
        beta = (log_hl_1 ** 2) + (log_hl_2 ** 2)

        # 2 Günlük bileşik aralık: Gamma
        h_2day = max(h1, h2)
        l_2day = min(l1, l2)
        log_hl_2day = math.log(h_2day / l_2day)
        gamma = log_hl_2day ** 2

        # Alfa Hesabı
        sqrt_2 = math.sqrt(2.0)
        denom = 3.0 - (2.0 * sqrt_2)
        num = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / denom - math.sqrt(gamma / denom)
        alpha = max(0.0, num)

        # Efektif Spread Formülü: S = 2 * (e^alpha - 1) / (1 + e^alpha)
        exp_alpha = math.exp(alpha)
        spread = 2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)

        # Negatif veya uçucu değerleri sınırla [0, %5]
        return max(0.0005, min(0.05, spread))
