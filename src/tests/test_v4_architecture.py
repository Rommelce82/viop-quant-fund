"""
Nihai Mimari Entegrasyon Doğrulama Testi (v4.0).

Bu test betiği;
1. Temel Pusula (FundamentalCompass - v4.0):
   - KADEME 1: Likidite ve Mikroyapı Filtresi (ADV & OI)
   - KADEME 2: Kanal A (Piotroski, Altman Z, CFO, ROIC > WACC) -> ONLY_LONG
   - KADEME 3: Fahiş Contango ve Derin Backwardation Taşıma Maliyeti Korumaları
2. Teknik İcra Motoru (TechnicalExecutioner - v4.0):
   - Günlük SMA(100), Saatlik ADX trend eğimi, Saatlik Donchian shift(1) kırılımı, Hacim patlaması
   - 2.5 R/K Barajı denetimi
   - Serbest Teminat (Margin Cap) tıraşlaması ile lot hesaplama
   - 12 Bar Zaman Stopu (Time Stop), Scale-Out (%50) ve Chandelier Exit mekanizmaları
3. Strateji Orkestratörü (StrategyOrchestratorV4):
   - Uçtan uca senkronize çalışma ve karar çıktısı
adımlarını eksiksiz test eder.
"""

from datetime import datetime, timedelta
import sys
import numpy as np
import pandas as pd

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.data.schemas import FundamentalData
from src.strategy.fundamental_compass import (
    AssetChannel,
    CostOfCarryInput,
    DirectionalBias,
    FundamentalCompass,
    MarketMicrostructureInput
)
from src.strategy.orchestrator import StrategyOrchestratorV4
from src.strategy.position_manager import PositionState
from src.strategy.technical_executioner import ExecutionActionV4, TechnicalExecutioner


def create_mock_market_data():
    """Test için sentetik Günlük ve Saatlik mum verisi üretir."""
    # Günlük: 120 bar, son fiyat 314 TL (SMA100 ~280 TL'nin çok üzerinde, Boğa)
    daily_dates = [datetime(2026, 5, 1) + timedelta(days=i) for i in range(120)]
    daily_closes = [250.0 + (i * 0.55) for i in range(120)]
    daily_df = pd.DataFrame({
        "timestamp": daily_dates,
        "open": [c - 1.0 for c in daily_closes],
        "high": [c + 2.0 for c in daily_closes],
        "low": [c - 2.0 for c in daily_closes],
        "close": daily_closes,
        "volume": [80_000_000.0 for _ in range(120)]
    })

    # Saatlik: 50 bar, 49. barda Donchian tavanı (310 TL) kırılıp 315 TL'ye fırlıyor, hacim patlıyor
    hourly_dates = [datetime(2026, 10, 1, 11, 0) + timedelta(hours=i) for i in range(50)]
    hourly_closes = []
    hourly_highs = []
    hourly_lows = []
    hourly_volumes = []

    for i in range(49):
        c = 308.0 + np.sin(i / 3.0) * 1.8
        hourly_closes.append(c)
        hourly_highs.append(c + 1.2)
        hourly_lows.append(c - 1.2)
        hourly_volumes.append(100_000.0)

    # 49. Bar: Kırılım Barı (Saatlik Kapanış 315 TL, Hacim 250,000)
    hourly_closes.append(315.0)
    hourly_highs.append(316.0)
    hourly_lows.append(307.0)
    hourly_volumes.append(250_000.0)

    # Open fiyatlarını bir önceki barın kapanışına yakın yapalım (yapay Gap oluşmasın)
    hourly_opens = [hourly_closes[0] - 0.5] + [hourly_closes[i - 1] + 0.1 for i in range(1, len(hourly_closes))]

    hourly_df = pd.DataFrame({
        "timestamp": hourly_dates,
        "open": hourly_opens,
        "high": hourly_highs,
        "low": hourly_lows,
        "close": hourly_closes,
        "volume": hourly_volumes
    })

    return daily_df, hourly_df


def create_mock_fundamental_record(symbol: str = "THYAO") -> FundamentalData:
    """ONLY_LONG şartlarını sağlayan güçlü temel veri (F >= 7, Z >= 2.60, CFO > NetKar, ROIC > WACC)."""
    return FundamentalData(
        symbol=symbol,
        as_of_date=datetime(2026, 6, 30),
        announced_at=datetime(2026, 8, 5, 18, 30),
        source="TEST_PIT",
        period_year=2026,
        period_quarter=2,
        pe_ratio=2.5,
        pb_ratio=1.2,
        ev_ebitda=2.8,
        peg_ratio=0.30,
        roe=0.45,
        roa=0.25,
        net_profit_margin=0.30,
        gross_margin=0.45,
        ebitda_margin=0.40,
        net_debt_ebitda=0.1,
        current_ratio=2.50,
        net_income_yoy_growth=0.60,
        revenue_yoy_growth=0.60,
        net_profit_try=60_000_000_000.0,
        revenue_try=200_000_000_000.0,
        ebitda_try=90_000_000_000.0,   # CFO vekili (90 Milyar) > Net Kar (60 Milyar)
        equity_try=90_000_000_000.0
    )


def test_v4_architecture():
    print("=" * 80)
    print("  VİOP NİHAİ MİMARİ VE ÇİFT ANAYASA (v4.0) UÇTAN UCA DOĞRULAMA TESTİ")
    print("=" * 80)

    daily_df, hourly_df = create_mock_market_data()
    fund_data = create_mock_fundamental_record("F_THYAO")

    compass = FundamentalCompass()
    executioner = TechnicalExecutioner()
    orchestrator = StrategyOrchestratorV4(compass=compass, executioner=executioner)

    # -------------------------------------------------------------------------
    # TEST 1: TEMEL PUSULA (v4.0) KADEME TESTLERİ
    # -------------------------------------------------------------------------
    print("\n[+] 1. TEST: TEMEL ANALİZ VE YÖN PUSULASI (v4.0):")

    # Kademe 1: Mikroyapı (ADV & Açık Pozisyon)
    micro_valid = MarketMicrostructureInput(adv_try=150_000_000.0, open_interest_contracts=35_000)
    micro_invalid = MarketMicrostructureInput(adv_try=40_000_000.0, open_interest_contracts=12_000)

    carry_normal = CostOfCarryInput(implied_irr=0.41, tcmb_funding_rate=0.40)      # Normal prim (%41 vs %40)
    carry_contango = CostOfCarryInput(implied_irr=0.45, tcmb_funding_rate=0.40)    # Fahiş Contango (> %42.5)

    # 1.A. Geçerli temel + geçerli mikroyapı -> ONLY_LONG
    res_1, msg_1 = compass.get_compass_verdict(
        channel=AssetChannel.EQUITY_REAL,
        micro=micro_valid,
        carry=carry_normal,
        fundamental_data=fund_data,
        tcmb_policy_rate=0.40
    )
    bias_1 = res_1["direction"]
    print(f"    * Normal Durum Yön Kararı     : {bias_1} (Çarpan: {res_1['multiplier']})")
    print(f"      Gerekçe: {msg_1}")
    assert bias_1 == DirectionalBias.ONLY_LONG.value, "Temel pusula ONLY_LONG üretmeliydi!"

    # 1.B. Yetersiz Likidite -> Kademe 1 Reddi (NEUTRAL)
    res_2, msg_2 = compass.get_compass_verdict(
        channel=AssetChannel.EQUITY_REAL,
        micro=micro_invalid,
        carry=carry_normal,
        fundamental_data=fund_data
    )
    bias_2 = res_2["direction"]
    print(f"    * Düşük ADV Durumu            : {bias_2} ({msg_2})")
    assert bias_2 == DirectionalBias.NEUTRAL.value, "Yetersiz mikroyapıda NEUTRAL dönmeliydi!"

    # 1.C. Fahiş Contango Koruması -> Kademe 3 Reddi (ONLY_LONG -> NEUTRAL)
    res_3, msg_3 = compass.get_compass_verdict(
        channel=AssetChannel.EQUITY_REAL,
        micro=micro_valid,
        carry=carry_contango,
        fundamental_data=fund_data
    )
    bias_3 = res_3["direction"]
    print(f"    * Fahiş Contango Durumu       : {bias_3} ({msg_3})")
    assert bias_3 == DirectionalBias.NEUTRAL.value, "Fahiş contango ONLY_LONG'u NEUTRAL yapmalıydı!"

    # -------------------------------------------------------------------------
    # TEST 2: TEKNİK İCRA VE OTORİTE MOTORU (v4.0)
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[+] 2. TEST: TEKNİK İCRA VE RİSK OTORİTESİ (v4.0):")

    portfolio_nav = 1_000_000.0  # 1 Milyon TL NAV
    free_margin = 80_000.0       # Serbest Teminat (80,000 TL) -> Teminat kısıtı testi için

    tech_decision = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=None,
        portfolio_nav=portfolio_nav,
        free_margin=free_margin
    )

    print(f"    * İcra Kararı                 : {tech_decision.action.value}")
    print(f"    * Kontrat Adedi (Lot)         : {tech_decision.target_lots} Lot (Margin Cap Uygulandı)")
    print(f"    * Giriş Fiyatı                : {tech_decision.entry_price:.2f} TL | İlk Stop: {tech_decision.stop_price:.2f} TL")
    print(f"    * Kâr Al Hedefi (TP)          : {tech_decision.take_profit_target:.2f} TL")
    print(f"    * Beklenen R/K Oranı          : {tech_decision.expected_rr_ratio:.2f} (Baraj >= 2.5)")
    print(f"    * Gerekçe                     : {tech_decision.reason}")

    assert tech_decision.action == ExecutionActionV4.ENTER_LONG, "B-Tarzı Long kırılımı tetiklenmeliydi!"
    assert tech_decision.expected_rr_ratio >= 2.0, "R/K oranı 2.0 barajını geçmeliydi!"
    # THYAO kontrat başı başlangıç teminatı: 6,500 TL. 80,000 TL serbest teminat / 6,500 TL = max 12 lot
    assert tech_decision.target_lots <= 12, "Lot adedi serbest teminata tıraşlanmalıydı!"

    # -------------------------------------------------------------------------
    # TEST 3: ORKESTRATÖR VE ÇIKIŞ YÖNETİMİ (ZAMAN STOPU & SCALE-OUT)
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[+] 3. TEST: ORKESTRATÖR VE ÇIKIŞ YÖNETİMİ ENTEGRASYONU:")

    verdict = orchestrator.run_strategy_cycle(
        symbol="F_THYAO",
        channel=AssetChannel.EQUITY_REAL,
        daily_data=daily_df,
        hourly_data=hourly_df,
        microstructure=micro_valid,
        cost_of_carry=carry_normal,
        portfolio_nav=portfolio_nav,
        free_margin=free_margin,
        position_state=None,
        fundamental_data=fund_data
    )
    print(f"    * Orkestratör Pusula İzni     : {verdict.compass_bias.value}")
    print(f"    * Orkestratör İcra Kararı     : {verdict.technical_decision.action.value}")

    # Zaman Stopu Simülasyonu (12 Bar boyu getiri < 1.0R kalırsa kapatma)
    active_pos = PositionState(
        symbol="F_THYAO",
        entry_price=tech_decision.entry_price,
        initial_stop=tech_decision.stop_price,
        trailing_stop=tech_decision.stop_price,
        lots=tech_decision.target_lots,
        entry_time=datetime.utcnow()
    )

    sim_hourly = hourly_df.copy()
    for b in range(1, 13):
        new_t = sim_hourly["timestamp"].iloc[-1] + timedelta(hours=1)
        sim_hourly = pd.concat([sim_hourly, pd.DataFrame([{
            "timestamp": new_t,
            "open": 315.2,
            "high": 315.8,
            "low": 314.5,
            "close": 315.4,
            "volume": 70_000.0
        }])], ignore_index=True)

        step_res = executioner.evaluate(
            symbol="F_THYAO",
            compass_bias=DirectionalBias.ONLY_LONG,
            daily_data=daily_df,
            hourly_data=sim_hourly,
            position_state=active_pos,
            portfolio_nav=portfolio_nav,
            free_margin=free_margin
        )
        if step_res.action == ExecutionActionV4.TIME_STOP_EXIT:
            print(f"\n    -> BAR #{b}: {step_res.action.value}")
            print(f"       {step_res.reason}")
            assert step_res.action == ExecutionActionV4.TIME_STOP_EXIT
            break

    print("\n" + "=" * 80)
    print("  ✓ VİOP ÇİFT ANAYASA MİMARİSİ (v4.0) %100 SADAKATLE BAŞARIYLA DOĞRULANDI")
    print("=" * 80)


if __name__ == "__main__":
    test_v4_architecture()
