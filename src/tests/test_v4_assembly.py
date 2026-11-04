"""
V4.0 Nihai Mimari Montaj ve Birim Testleri (test_v4_assembly.py).
Referans Modüller:
- TechnicalExecutionerV4 & ExecutionActionV4 (technical_executioner.py)
- PositionManagerV4 & PositionState (position_manager.py)
- PortfolioRiskManagerV4 (portfolio_manager.py)
"""

import math
import pytest
from src.strategy.technical_executioner import TechnicalExecutionerV4, ExecutionActionV4
from src.strategy.position_manager import PositionManagerV4, PositionState
from src.strategy.portfolio_manager import PortfolioRiskManagerV4


def test_v4_fx_carry_only_lockout():
    """Döviz ve DXY çiftlerinde çıplak breakout engeli (REJECT_FX_CARRY_ONLY) testi."""
    engine = TechnicalExecutionerV4()
    mock_bar = {
        'close': [35.0, 35.5],
        'open': [34.8, 35.0],
        'high': [35.2, 35.6],
        'low': [34.7, 34.9],
        'volume': [1000, 2000],
        'vol_sma20': [1000, 1000],
        'atr14': [0.5, 0.5],
        'adx14': [25.0, 26.0],
        'donchian_high': [35.2, 35.2],
        'donchian_low': [34.0, 34.0],
        'total_aps': [100, 110]
    }
    mock_daily = {'close': [35.5], 'sma100': [34.0]}

    for sym in ["F_USDTRY", "F_EURTRY", "F_GBPTRY", "F_DXY", "F_EURUSD"]:
        res = engine.evaluate(sym, mock_bar, mock_daily)
        assert res["action"] == ExecutionActionV4.REJECT_FX_CARRY_ONLY


def test_v4_dual_engine_signals():
    """B-Tarzı Breakout ve A-Tarzı Mean-Reversion sinyal doğrulamaları."""
    engine = TechnicalExecutionerV4()

    # 1. B-Tarzı Long Kırılımı (F_XU030)
    bar_long_b = {
        'close': [10500.0, 10600.0],
        'open': [10450.0, 10510.0],
        'high': [10550.0, 10620.0],
        'low': [10400.0, 10490.0],
        'volume': [10000, 12000],
        'vol_sma20': [10000, 10000], # 12000 >= 1.15 * 10000 (Endeks)
        'atr14': [150.0, 150.0],
        'adx14': [18.0, 20.0],        # adx >= 15 and slope > 0
        'donchian_high': [10550.0, 10550.0], # close (10600) >= donchian_high[-2]
        'donchian_low': [10200.0, 10200.0],
        'total_aps': [50000, 52000]   # APS artışı
    }
    daily_bull = {'close': [10600.0], 'sma100': [10000.0]}
    res_long_b = engine.evaluate("F_XU030", bar_long_b, daily_bull)
    assert res_long_b["action"] == ExecutionActionV4.ENTER_LONG_B_TYPE
    assert res_long_b["entry_price"] == 10600.0
    assert res_long_b["stop_price"] == 10600.0 - (2.0 * 150.0)

    # 2. B-Tarzı Short Çöküş (F_THYAO, Daily Close < SMA100)
    bar_short_b = {
        'close': [280.0, 270.0],
        'open': [285.0, 278.0],
        'high': [286.0, 279.0],
        'low': [279.0, 269.0],
        'volume': [50000, 55000],
        'vol_sma20': [50000, 50000], # 55000 >= 1.0 * 50000
        'atr14': [8.0, 8.0],
        'adx14': [22.0, 24.0],
        'donchian_high': [310.0, 310.0],
        'donchian_low': [275.0, 275.0], # close (270) <= donchian_low[-2]
        'total_aps': [120000, 125000]
    }
    daily_bear = {'close': [270.0], 'sma100': [300.0]}
    res_short_b = engine.evaluate("F_THYAO", bar_short_b, daily_bear)
    assert res_short_b["action"] == ExecutionActionV4.ENTER_SHORT_B_TYPE
    assert res_short_b["entry_price"] == 270.0
    assert res_short_b["stop_price"] == 270.0 + (2.0 * 8.0)

    # 3. A-Tarzı Long Tepki (Yatay Piyasa: ADX < 15, Bollinger Alt Bandı + Yeşil Mum)
    bar_long_a = {
        'close': [300.0, 302.0],
        'open': [301.0, 299.0],      # close (302) > open (299) -> yeşil mum
        'high': [302.0, 303.0],
        'low': [298.0, 297.0],       # low (297) <= bollinger_lower (298)
        'volume': [30000, 32000],
        'vol_sma20': [30000, 30000],
        'atr14': [5.0, 5.0],
        'adx14': [12.0, 13.0],       # adx < 15
        'bollinger_lower': [298.0, 298.0],
        'donchian_high': [320.0, 320.0],
        'donchian_low': [295.0, 295.0]
    }
    res_long_a = engine.evaluate("F_GARAN", bar_long_a, daily_bull)
    assert res_long_a["action"] == ExecutionActionV4.ENTER_LONG_A_TYPE
    assert res_long_a["entry_price"] == 302.0
    assert res_long_a["stop_price"] == 302.0 - (1.5 * 5.0)


def test_v4_position_manager_lifecycle():
    """PositionManagerV4: Tapi retest marjı, %33 scale-out, chandelier stop, trend reversal, zaman stopu."""
    pm = PositionManagerV4()

    # LONG Pozisyon Testi
    pos_long = PositionState(
        symbol="F_THYAO",
        entry_price=300.0,
        initial_stop=290.0, # 1R = 10 TL
        trailing_stop=290.0,
        lots=9
    )

    daily_bull = {'close': [305.0], 'sma100': [280.0]}

    # Bar 1: Fiyat 310 TL (+1.0R kâr). Tapi Retest marjı: Stop -> Entry - 0.5 ATR (300 - 2.5 = 297.5)
    bar_tapi = {
        'close': 310.0,
        'high': 311.0,
        'low': 309.0,
        'atr14': 5.0,
        'highest_high_20': 311.0,
        'sma20': 302.0,
        'prev_close': 308.0,
        'prev_sma20': 301.0
    }
    res = pm.update_and_evaluate_exit(pos_long, bar_tapi, daily_bull)
    assert res["action"] == "HOLD"
    assert pos_long.is_breakeven_activated is True
    assert pos_long.stop_price >= (300.0 - 2.5)

    # Bar 2: Fiyat 321 TL (+2.1R kâr). %33 Scale-out: 9 lotun %33'ü = ceil(9 * 0.33) = 3 lot kapanır, 6 lot kalır
    bar_so = {
        'close': 321.0,
        'high': 322.0,
        'low': 319.0,
        'atr14': 5.0,
        'highest_high_20': 322.0,
        'sma20': 305.0,
        'prev_close': 315.0,
        'prev_sma20': 303.0
    }
    res_so = pm.update_and_evaluate_exit(pos_long, bar_so, daily_bull)
    assert res_so["action"] == "SCALE_OUT_33"
    assert res_so["closed_lots"] == 3
    assert pos_long.current_lots == 6
    assert pos_long.has_scaled_out_33 is True

    # Bar 3: Trend Reversal (SMA20 altı 2 ardışık bar)
    bar_rev = {
        'close': 295.0,
        'high': 298.0,
        'low': 294.0,
        'atr14': 5.0,
        'highest_high_20': 322.0,
        'sma20': 300.0,
        'prev_close': 297.0,
        'prev_sma20': 301.0
    }
    res_rev = pm.update_and_evaluate_exit(pos_long, bar_rev, daily_bull)
    assert res_rev["action"] == "CLOSE_TREND_REVERSAL"
    assert res_rev["lots"] == 6

    # SHORT Pozisyon Zaman Stopu Dondurma Testi
    pos_short = PositionState(
        symbol="F_THYAO",
        entry_price=300.0,
        initial_stop=310.0,
        trailing_stop=310.0,
        lots=-5
    )
    pos_short.bars_held = 30  # 30 bar doldu
    daily_bear = {'close': [285.0], 'sma100': [310.0]}

    # Eğer pozisyon kârdaysa (Close = 290 < Entry = 300), zaman stopu DONDURULUR (HOLD kalır)
    bar_short_profit = {
        'close': 290.0, # +1.0R kârda
        'high': 292.0,
        'low': 288.0,
        'atr14': 4.0,
        'lowest_low_20': 288.0,
        'sma20': 295.0,
        'prev_close': 292.0,
        'prev_sma20': 296.0
    }
    res_short_hold = pm.update_and_evaluate_exit(pos_short, bar_short_profit, daily_bear)
    assert res_short_hold["action"] == "HOLD"  # Kârlı olduğu için zaman stopu donduruldu!

    # Eğer pozisyon zarardaysa (Close = 305 > Entry = 300) ve trend tersine dönmemişse, zaman stopu çalışır
    bar_short_loss = {
        'close': 305.0,
        'high': 306.0,
        'low': 304.0,
        'atr14': 4.0,
        'lowest_low_20': 288.0,
        'sma20': 308.0,
        'prev_close': 304.0,
        'prev_sma20': 308.0
    }
    res_short_ts = pm.update_and_evaluate_exit(pos_short, bar_short_loss, daily_bear)
    assert res_short_ts["action"] == "CLOSE_TIME_STOP"


def test_v4_portfolio_risk_manager_vault():
    """PortfolioRiskManagerV4: İkili kasa mimarisi (Trade + ALE Repo) ve %2 NAV lot hesabı."""
    portfolio = PortfolioRiskManagerV4(initial_capital=150_000.0, repo_rate_annual=0.48)
    assert portfolio.trade_vault == 150_000.0
    assert portfolio.ale_safe_vault == 0.0

    # 1. Seans Sonu: 50.000 TL teminat kilitli, 100.000 TL serbest nakit ALE fonuna nemalanır (%17.5 stopaj kesintisi ile)
    daily_net_nema = portfolio.update_overnight_nema(total_margin_locked=50_000.0)
    expected_gross = 100_000.0 * (0.48 / 365.0)
    expected_tax = expected_gross * 0.175
    expected_net = expected_gross * (1.0 - 0.175)
    assert abs(daily_net_nema - expected_net) < 1e-4
    assert abs(portfolio.ale_safe_vault - expected_net) < 1e-4
    assert abs(portfolio.total_tax_paid - expected_tax) < 1e-4

    # 2. Konsolide NAV Hesabı
    nav = portfolio.get_consolidated_nav()
    assert nav == 150_000.0 + expected_net

    # 3. Lot Hesabı (%2 Risk Kuralı)
    # Entry: 300 TL, Stop: 290 TL -> Risk = 10 TL * 100 çarpan = 1000 TL / kontrat
    # NAV ~ 150.131 TL * 0.02 = ~3002.6 TL -> raw_lots = 3.0 -> ideal_lots = 3
    # Teminat: 6.500 TL -> max lots = 150.000 / 6.500 = 23
    lots = portfolio.calculate_lots(
        entry_price=300.0,
        stop_price=290.0,
        contract_multiplier=100.0,
        initial_margin_try=6500.0,
        vol_scale=1.0
    )
    assert lots == 3
