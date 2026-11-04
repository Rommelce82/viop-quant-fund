"""
Dual Engine (A-Tarzı & B-Tarzı), Tapi Retest Buffer, Scale-Out %33 ve İcra Kuralları Testi.
(test_dual_engine_rules.py)
"""

from datetime import datetime, timedelta
import pandas as pd
import pytest

from src.strategy.fundamental_compass import DirectionalBias
from src.strategy.position_manager import PositionState
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalExecutioner
)
from src.tests.test_v4_architecture import create_mock_market_data


def test_dual_engine_b_and_a_types():
    """B-Tarzı kırılım ve A-Tarzı destek tepkisi testleri."""
    executioner = TechnicalExecutioner()
    daily_df, hourly_df = create_mock_market_data()

    # 1. B-Tarzı Long Kırılımı (ADX >= 15 ve Donchian tavanı aşılmış)
    dec_b = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=None,
        portfolio_nav=150_000.0,
        free_margin=150_000.0
    )
    assert dec_b.action == ExecutionActionV4.ENTER_LONG
    assert dec_b.expected_rr_ratio >= 2.0

    # 2. Döviz VİOP (USDTRY) Çıplak Breakout Blokajı
    dec_try = executioner.evaluate(
        symbol="F_USDTRY",
        compass_bias=DirectionalBias.BI_DIRECTIONAL,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=None,
        portfolio_nav=150_000.0,
        free_margin=150_000.0
    )
    assert dec_try.action == ExecutionActionV4.REJECT_FX_CARRY_ONLY


def test_tapi_and_scale_out_33():
    """+1.0R Tapi Retest Marjı ve +2.0R %33 Scale-Out testleri."""
    executioner = TechnicalExecutioner()
    daily_df, hourly_df = create_mock_market_data()

    entry_p = 310.0
    stop_p = 300.0  # 1R = 10 TL
    r_unit = 10.0

    pos = PositionState(
        symbol="F_THYAO",
        entry_price=entry_p,
        initial_stop=stop_p,
        trailing_stop=stop_p,
        lots=10,
        entry_time=datetime(2026, 10, 1, 10, 0),
        r_unit_price=r_unit
    )

    # A. +1.2R kâr durumu: Fiyat 322 TL -> Tapi marjı devreye girmeli (Entry - 0.5 ATR)
    hourly_tapi = hourly_df.copy()
    idx = hourly_tapi.index[-1]
    hourly_tapi.loc[idx, "close"] = 322.0
    hourly_tapi.loc[idx, "high"] = 323.0
    hourly_tapi.loc[idx, "low"] = 321.0

    dec_tapi = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_tapi,
        position_state=pos,
        portfolio_nav=150_000.0,
        free_margin=150_000.0
    )
    # Stop seviyesi initial stop'un üzerine, entry - 0.5*ATR seviyesine çekilmiş olmalı
    assert pos.trailing_stop > stop_p
    assert pos.trailing_stop >= (entry_p - 5.0)

    # B. +2.2R kâr durumu: Fiyat 332 TL -> %33 Scale-Out gerçekleşmeli (10 lotun %33'ü = 3 lot)
    hourly_so = hourly_df.copy()
    hourly_so.loc[idx, "close"] = 332.0
    hourly_so.loc[idx, "high"] = 333.0
    hourly_so.loc[idx, "low"] = 331.0

    dec_so = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_so,
        position_state=pos,
        portfolio_nav=150_000.0,
        free_margin=150_000.0
    )
    assert dec_so.action == ExecutionActionV4.SCALE_OUT_33
    assert dec_so.target_lots == 3
    assert dec_so.metrics["remaining_lots"] == 7  # Önerilen kalan lot (%67)
    # İcra katmanı emri uyguladığında pozisyon lotu güncellenir
    pos.lots -= dec_so.target_lots
    pos.scaled_out = True
    assert pos.lots == 7


def test_trend_reversal_exit():
    """Fiyat SMA20 altında 2 ardışık bar kapattığında koşulsuz Trend Reversal Exit testi."""
    executioner = TechnicalExecutioner()
    daily_df, hourly_df = create_mock_market_data()

    pos = PositionState(
        symbol="F_THYAO",
        entry_price=310.0,
        initial_stop=300.0,
        trailing_stop=305.0,
        lots=5,
        entry_time=datetime(2026, 10, 1, 10, 0),
        r_unit_price=10.0
    )

    # SMA20'nin altında 2 ardışık bar kapanışı
    hourly_rev = hourly_df.copy()
    hourly_rev.loc[hourly_rev.index[-2], "close"] = 295.0
    hourly_rev.loc[hourly_rev.index[-2], "open"] = 297.0
    hourly_rev.loc[hourly_rev.index[-1], "close"] = 294.0
    hourly_rev.loc[hourly_rev.index[-1], "open"] = 296.0

    dec_rev = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_rev,
        position_state=pos,
        portfolio_nav=150_000.0,
        free_margin=150_000.0
    )
    assert dec_rev.action == ExecutionActionV4.TREND_REVERSAL_EXIT
    assert "Trend Reversal" in dec_rev.reason
