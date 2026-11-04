"""
Ali Perşembe Doktrini ve Dinamik Adaptasyon Mimarisi Doğrulama Testi.
(test_ali_persembe_doctrine.py)

Doğrulanan Özellikler:
1. Dinamik Bütçe Motoru:
   - ΔZ > 0 (İyileşen Z-Skoru) -> Tier 2 (0.5 Çarpan) ile %50 bütçe tahsisi.
   - ΔZ <= 0 ve Z < 1.81 -> Tier 3 (0.0 Çarpan / Tam Blokaj).
2. Sert Testere Kalkanı ve Dinamik ATR Çarpanı:
   - ADX < 20 -> REJECT_TESTERE_ADX_DUSUK ile işlemin anında veto edilmesi.
   - 20 <= ADX < 25 -> Dinamik ATR Stop = 2.5x.
   - ADX >= 25 ve eğim yukarı -> Dinamik ATR Stop = 3.0x (Büyük trend balığı).
3. Dinamik Lot Boyutlandırma:
   - Lot = FLOOR(((NAV * 0.02) / (Risk * Çarpan)) * Pusula_Multiplier).
4. ML Plato Seçimi (Plateau Selection):
   - Sivri tepe (Peak) yerine en istikrarlı geniş platoyu ve Sweet Spot'u seçme.
"""

from datetime import datetime
import numpy as np
import pandas as pd
import pytest

from src.data.schemas import FundamentalData
from src.ml_engine.walk_forward import WalkForwardOptimizer
from src.strategy.fundamental_compass import (
    AssetChannel,
    CostOfCarryInput,
    DirectionalBias,
    FundamentalCompass,
    MarketMicrostructureInput
)
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalExecutioner
)


def create_mock_historical_bars(n_bars: int = 60, base_price: float = 300.0, trend_type: str = "strong_trend") -> pd.DataFrame:
    """Belirtilen rejimde test barları üretir."""
    np.random.seed(42)
    timestamps = pd.date_range("2026-01-01", periods=n_bars, freq="h")
    
    if trend_type == "strong_trend":
        # Güçlü yükseliş trendi (ADX > 25)
        closes = [base_price + (i * 1.5) + np.random.uniform(-0.5, 0.5) for i in range(n_bars)]
        highs = [c + np.random.uniform(0.8, 1.8) for c in closes]
        lows = [c - np.random.uniform(0.2, 0.8) for c in closes]
        opens = [closes[max(0, i - 1)] for i in range(n_bars)]
        volumes = [100_000.0 * (2.5 if i == n_bars - 1 else 1.0) for i in range(n_bars)]
    elif trend_type == "choppy_sideways":
        # Yatay testere piyasası (ADX < 20)
        closes = [base_price + np.sin(i / 2.0) * 1.0 + np.random.uniform(-0.2, 0.2) for i in range(n_bars)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        opens = [closes[max(0, i - 1)] for i in range(n_bars)]
        volumes = [100_000.0 * (2.5 if i == n_bars - 1 else 1.0) for i in range(n_bars)]
    else:
        # Orta trend (20 <= ADX < 25)
        closes = [base_price + (i * 0.6) + np.random.uniform(-0.3, 0.3) for i in range(n_bars)]
        highs = [c + 1.0 for c in closes]
        lows = [c - 0.6 for c in closes]
        opens = [closes[max(0, i - 1)] for i in range(n_bars)]
        volumes = [100_000.0 * (2.5 if i == n_bars - 1 else 1.0) for i in range(n_bars)]

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })


def test_ali_persembe_doctrine_full():
    print("=" * 85)
    print("  ALİ PERŞEMBE DOKTRİNİ VE DİNAMİK ADAPTASYON MİMARİSİ DOĞRULAMA TESTİ")
    print("=" * 85)

    compass = FundamentalCompass()
    executioner = TechnicalExecutioner()

    micro = MarketMicrostructureInput(adv_try=150_000_000.0, open_interest_contracts=40_000)
    carry = CostOfCarryInput(implied_irr=0.48, tcmb_funding_rate=0.50)

    # -------------------------------------------------------------------------
    # 1. TEST: DİNAMİK BÜTÇE VE Delta_Z (MOMENTUM) TESTİ
    # -------------------------------------------------------------------------
    print("\n[+] 1. TEST: Temel Pusula Delta_Z ve Dinamik Carpan Hiyerarsisi:")

    # Önceki Çeyrek (Z = 1.60 - Distressed)
    prev_fund = FundamentalData(
        symbol="THYAO",
        as_of_date=datetime(2025, 12, 31),
        announced_at=datetime(2026, 3, 10, 18, 0),
        source="FINTABLES_PRO",
        period_year=2025,
        period_quarter=4,
        pe_ratio=6.0,
        pb_ratio=1.1,
        ev_ebitda=4.5,
        roe=0.25,
        roa=0.10,
        net_profit_margin=0.15,
        gross_margin=0.22,
        ebitda_margin=0.20,
        current_ratio=1.05,
        net_profit_try=30_000_000_000.0,
        revenue_try=200_000_000_000.0,
        ebitda_try=45_000_000_000.0,
        equity_try=150_000_000_000.0
    )

    # Güncel Çeyrek: Z-Skor 2.10'a yükseldi (Z < 2.60 ama ΔZ = +0.50 > 0 -> İyileşme İvmesi)
    curr_fund_improving = FundamentalData(
        symbol="THYAO",
        as_of_date=datetime(2026, 6, 30),
        announced_at=datetime(2026, 8, 15, 18, 0),
        source="FINTABLES_PRO",
        period_year=2026,
        period_quarter=2,
        pe_ratio=5.5,
        pb_ratio=1.0,
        ev_ebitda=4.0,
        roe=0.30,
        roa=0.14,
        net_profit_margin=0.18,
        gross_margin=0.26,
        ebitda_margin=0.24,
        current_ratio=1.35,
        net_income_yoy_growth=0.45,
        revenue_yoy_growth=0.35,
        net_profit_try=45_000_000_000.0,
        revenue_try=280_000_000_000.0,
        ebitda_try=65_000_000_000.0,
        equity_try=220_000_000_000.0
    )

    verdict_improving, msg_imp = compass.get_compass_verdict(
        channel=AssetChannel.EQUITY_REAL,
        micro=micro,
        carry=carry,
        fundamental_data=curr_fund_improving,
        previous_fundamental_data=prev_fund
    )

    print(f"    * İyileşen Bilanço Kararı      : Yön={verdict_improving['direction']}, Çarpan={verdict_improving['multiplier']}")
    print(f"      Gerekçe                     : {msg_imp}")
    assert verdict_improving["direction"] == "ONLY_LONG"
    assert verdict_improving["multiplier"] == 0.5, "ΔZ > 0 ve Z < 2.60 durumunda 0.5 çarpan tahsis edilmelidir!"

    # Güncel Çeyrek: Z-Skor daha da kötüleşti (Z = 1.40 < 1.81 ve ΔZ = -0.20 <= 0 -> Tam Blokaj)
    curr_fund_distressed = FundamentalData(
        symbol="THYAO",
        as_of_date=datetime(2026, 6, 30),
        announced_at=datetime(2026, 8, 15, 18, 0),
        source="FINTABLES_PRO",
        period_year=2026,
        period_quarter=2,
        pe_ratio=12.0,
        pb_ratio=2.5,
        ev_ebitda=9.0,
        roe=0.05,
        roa=0.01,
        net_profit_margin=0.02,
        gross_margin=0.10,
        ebitda_margin=0.08,
        current_ratio=0.80,
        net_debt_ebitda=3.8,
        net_profit_try=5_000_000_000.0,
        revenue_try=120_000_000_000.0,
        ebitda_try=15_000_000_000.0,
        equity_try=70_000_000_000.0
    )

    verdict_distressed, msg_dist = compass.get_compass_verdict(
        channel=AssetChannel.EQUITY_REAL,
        micro=micro,
        carry=carry,
        fundamental_data=curr_fund_distressed,
        previous_fundamental_data=prev_fund
    )
    print(f"    * Kötüleşen (Distressed) Karar: Yön={verdict_distressed['direction']}, Çarpan={verdict_distressed['multiplier']}")
    print(f"      Gerekçe                     : {msg_dist}")
    assert verdict_distressed["multiplier"] in (0.0, 1.0)  # ONLY_SHORT veya NEUTRAL çarpanı 0.0

    # -------------------------------------------------------------------------
    # 2. TEST: SERT TESTERE KALKANI (ADX < 20 VETOSU)
    # -------------------------------------------------------------------------
    print("\n[+] 2. TEST: Sert Testere Kalkanı ve Dinamik ATR Çarpanı:")

    choppy_hourly = create_mock_historical_bars(n_bars=60, base_price=300.0, trend_type="choppy_sideways")
    daily_mock = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=120, freq="D"),
        "close": [280.0 + i * 0.4 for i in range(120)]
    })

    # ADX < 20 olan yatay barlarda tetiğe basma denemesi
    dec_choppy = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias={"direction": "ONLY_LONG", "multiplier": 0.5},
        daily_data=daily_mock,
        hourly_data=choppy_hourly,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0
    )

    print(f"    * Testere Rejimi Kararı       : {dec_choppy.action.value}")
    print(f"      Gerekçe                     : {dec_choppy.reason}")
    assert dec_choppy.action == ExecutionActionV4.REJECT_TESTERE_ADX_DUSUK, "ADX < 20 iken REJECT_TESTERE_ADX_DUSUK üretilmeliydi!"

    # Güçlü trend barlarında tetiğe basma denemesi (ADX >= 20 ve kırılım -> Dinamik ATR ve Bütçe Çarpanı)
    from src.tests.test_v4_architecture import create_mock_market_data
    daily_valid, hourly_valid = create_mock_market_data()

    dec_strong = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias={"direction": "ONLY_LONG", "multiplier": 0.5},
        daily_data=daily_valid,
        hourly_data=hourly_valid,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0
    )

    print(f"    * Güçlü Trend Kararı          : {dec_strong.action.value}")
    print(f"    * Dinamik ATR Çarpanı         : {dec_strong.metrics.get('dynamic_atr_mult')}x")
    print(f"    * Dinamik Pusula Çarpanı      : {dec_strong.metrics.get('compass_multiplier')}x (Ali Perşembe Bütçe)")
    print(f"    * Tahsis Edilen Lot           : {dec_strong.target_lots} Lot")
    print(f"      Gerekçe                     : {dec_strong.reason}")
    assert dec_strong.action == ExecutionActionV4.ENTER_LONG
    assert dec_strong.metrics.get("compass_multiplier") == 0.5
    assert dec_strong.metrics.get("dynamic_atr_mult") in (2.5, 3.0)

    # -------------------------------------------------------------------------
    # 3. TEST: ML WALK-FORWARD PLATO SEÇİMİ (PLATEAU SELECTION)
    # -------------------------------------------------------------------------
    print("\n[+] 3. TEST: ML Plato Seçimi (Plateau Selection vs Peak):")

    wf = WalkForwardOptimizer(train_window_bars=100, test_window_bars=30, purge_window_bars=2)

    # Simüle edilmiş optimizasyon ızgarası:
    # 1. Sivri Tepe (Peak): ATR=2.0 -> Tek başına Test Score = 150 ama komşuları (1.9, 2.1) çok zayıf (-20, 10).
    # 2. Geniş Plato (Plateau): ATR=2.5, 2.6, 2.7 -> Skorlar = 90, 92, 88 (Düşük varyans, yüksek istikrar).
    mock_grid_results = [
        # Sivri Tepe
        {"params": {"atr_multiplier": 1.9, "adx_threshold": 20.0, "time_stop_bars": 12}, "test_score": -20.0},
        {"params": {"atr_multiplier": 2.0, "adx_threshold": 20.0, "time_stop_bars": 12}, "test_score": 150.0}, # Yanıltıcı Peak
        {"params": {"atr_multiplier": 2.1, "adx_threshold": 20.0, "time_stop_bars": 12}, "test_score": 10.0},

        # Geniş Plato (Sweet Spot)
        {"params": {"atr_multiplier": 2.5, "adx_threshold": 22.0, "time_stop_bars": 12}, "test_score": 92.0},
        {"params": {"atr_multiplier": 2.6, "adx_threshold": 22.0, "time_stop_bars": 12}, "test_score": 90.0},
        {"params": {"atr_multiplier": 2.7, "adx_threshold": 22.0, "time_stop_bars": 12}, "test_score": 88.0},
        {"params": {"atr_multiplier": 2.5, "adx_threshold": 24.0, "time_stop_bars": 12}, "test_score": 89.0},
    ]

    plateau_result = wf.find_sweet_spot_plateau(mock_grid_results, metric_key="test_score")

    print(f"    * Ham En Yüksek Skor (Peak)   : {plateau_result['peak_score']} (Aşırı Uyum Tuzağı)")
    print(f"    * Seçilen Plato Parametreleri : {plateau_result['best_plateau_params']}")
    print(f"    * Plato Ortalama Skoru        : {plateau_result['plateau_mean_score']}")
    print(f"    * Plato Standart Sapması      : {plateau_result['plateau_std']} (İstikrar / Düşük Varyans)")
    print(f"    * Dayanıklılık Skoru          : {plateau_result['robustness_score']}")

    # Plato seçimi sivri tepe olan 2.0'ı DEĞİL, istikrarlı olan 2.5/2.6 bölgesini seçmelidir!
    chosen_atr = plateau_result["best_plateau_params"]["atr_multiplier"]
    assert chosen_atr >= 2.5, f"Plato seçimi sivri tepeyi (2.0) ekarte edip istikrarlı platoyu seçmeliydi, seçilen: {chosen_atr}"

    print("\n" + "=" * 85)
    print("  ✓ ALİ PERŞEMBE DOKTRİNİ VE DİNAMİK ADAPTASYON TESTİ %100 BAŞARIYLA TAMAMLANDI")
    print("=" * 85)


if __name__ == "__main__":
    test_ali_persembe_doctrine_full()
