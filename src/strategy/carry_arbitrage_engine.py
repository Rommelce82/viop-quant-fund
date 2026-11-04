"""
Döviz / FX VİOP Zımni Faiz ve Carry Arbitraj Motoru
(src/strategy/carry_arbitrage_engine.py).

Ali Perşembe Doktrini:
- Müdahaleli kur rejimlerinde çıplak teknik kırılım (Breakout) sahte al-sat zararlarına (Whipsaw) yol açar.
- Bunun yerine:
  1. BIST Vadeli Döviz Zımni Faizi (Implied Interest Rate - IRR) hesaplanır:
     IRR = ((Vadeli_Fiyat / Spot_Fiyat) - 1) * (365 / Gun_Sayisi)
  2. BIST Zımni Faizi ile TCMB Fonlama / Repo Faizi (veya ALE Repo Getirisi) karşılaştırılır:
     - Fahiş Contango (IRR > Repo + %2.50): Spot Al + Vadeli Sat (Cash-and-Carry Arbitrajı).
     - Derin Backwardation (IRR < Repo - %2.50): Vadeli Al + Spot Sat (Reverse Cash-and-Carry).
     - Makas normal aralıktaysa çıplak işlem açılmaz; serbest nakit Akbank ALE Para Piyasası Fonu'nda (%48 brüt nema) değerlendirilir.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class CarryArbitrageSignal:
    symbol: str
    spot_price: float
    futures_price: float
    days_to_expiry: int
    implied_irr: float
    benchmark_repo_rate: float
    spread_bps: float
    action: str  # 'CASH_AND_CARRY', 'REVERSE_CARRY', 'ALE_REPO_HOLD'
    is_arbitrage_active: bool
    expected_annual_return: float
    reason: str


class CarryArbitrageEngine:
    """
    VİOP FX Sözleşmeleri İçin Zımni Faiz Arbitraj ve Taşıma Maliyeti Motoru.
    """

    ARBITRAGE_SPREAD_THRESHOLD = 0.025  # 250 bps (%2.50) Arbitraj Eşiği

    def __init__(self, benchmark_repo_rate: float = 0.48) -> None:
        """
        Args:
            benchmark_repo_rate: Karşılaştırma repo faizi (Varsayılan: %48.00 Akbank ALE / TCMB Fonlama)
        """
        self.benchmark_repo_rate = benchmark_repo_rate

    def evaluate_carry(
        self,
        symbol: str,
        spot_price: float,
        futures_price: float,
        days_to_expiry: int = 30
    ) -> CarryArbitrageSignal:
        """
        Zımni faiz oranını hesaplar ve arbitraj fırsatını değerlendirir.
        """
        if spot_price <= 0 or days_to_expiry <= 0:
            return CarryArbitrageSignal(
                symbol=symbol,
                spot_price=spot_price,
                futures_price=futures_price,
                days_to_expiry=days_to_expiry,
                implied_irr=0.0,
                benchmark_repo_rate=self.benchmark_repo_rate,
                spread_bps=0.0,
                action="ALE_REPO_HOLD",
                is_arbitrage_active=False,
                expected_annual_return=self.benchmark_repo_rate,
                reason="Geçersiz fiyat veya vade girdisi."
            )

        # Yıllıklandırılmış Zımni Getiri (Implied IRR)
        raw_basis = (futures_price / spot_price) - 1.0
        implied_irr = raw_basis * (365.0 / days_to_expiry)
        spread = implied_irr - self.benchmark_repo_rate
        spread_bps = spread * 10_000.0

        # Fırsat Değerlendirmesi
        if spread >= self.ARBITRAGE_SPREAD_THRESHOLD:
            return CarryArbitrageSignal(
                symbol=symbol,
                spot_price=spot_price,
                futures_price=futures_price,
                days_to_expiry=days_to_expiry,
                implied_irr=implied_irr,
                benchmark_repo_rate=self.benchmark_repo_rate,
                spread_bps=spread_bps,
                action="CASH_AND_CARRY",
                is_arbitrage_active=True,
                expected_annual_return=implied_irr,
                reason=f"Fahiş Contango Fırsatı: Zımni Faiz (%{implied_irr*100:.2f}) > Repo Faizi (%{self.benchmark_repo_rate*100:.2f}) + {spread_bps:.0f} bps. Spot Al + Vadeli Sat Arbitrajı Tetiklendi."
            )
        elif spread <= -self.ARBITRAGE_SPREAD_THRESHOLD:
            return CarryArbitrageSignal(
                symbol=symbol,
                spot_price=spot_price,
                futures_price=futures_price,
                days_to_expiry=days_to_expiry,
                implied_irr=implied_irr,
                benchmark_repo_rate=self.benchmark_repo_rate,
                spread_bps=spread_bps,
                action="REVERSE_CARRY",
                is_arbitrage_active=True,
                expected_annual_return=self.benchmark_repo_rate - implied_irr,
                reason=f"Derin Backwardation Fırsatı: Zımni Faiz (%{implied_irr*100:.2f}) < Repo Faizi (%{self.benchmark_repo_rate*100:.2f}) - {abs(spread_bps):.0f} bps. Vadeli Al + Spot Sat Arbitrajı Tetiklendi."
            )
        else:
            return CarryArbitrageSignal(
                symbol=symbol,
                spot_price=spot_price,
                futures_price=futures_price,
                days_to_expiry=days_to_expiry,
                implied_irr=implied_irr,
                benchmark_repo_rate=self.benchmark_repo_rate,
                spread_bps=spread_bps,
                action="ALE_REPO_HOLD",
                is_arbitrage_active=False,
                expected_annual_return=self.benchmark_repo_rate,
                reason=f"Piyasa Fiyatlaması Adil (Zımni Faiz: %{implied_irr*100:.2f}, Repo: %{self.benchmark_repo_rate*100:.2f}). Çıplak işlem açılmaz; bakiye Akbank ALE Fonunda risksiz %48 nemada tutulur."
            )
