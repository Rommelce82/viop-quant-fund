"""
Test Suite: VİOP v4.2 Gelişmiş Özellikler (src/tests/test_v4_2_new_features.py).
1. Çift Taraflı Midas Komisyonu (Alış ve Satış)
2. Seans Pencereli 240m Barlar (14:15 ve 18:15)
3. Bedava Piramitleme (Free Pyramiding +2.0R %33 lot)
4. Roll-Over ve Calendar Spread Denetçisi
5. Carry Arbitraj ve Zımni Faiz Motoru
"""

from datetime import datetime
import pandas as pd
import pytest

from src.backtest.event_driven_tester import EventDrivenBacktester
from src.strategy.carry_arbitrage_engine import CarryArbitrageEngine
from src.strategy.position_manager import PositionState
from src.strategy.roll_over_manager import ViopRollOverManager


def test_double_sided_midas_commission_tiers():
    tester = EventDrivenBacktester()
    # 0 - 10M: %0.05
    assert tester.get_midas_commission_rate(5_000_000.0) == 0.0005
    # 10 - 100M: %0.02
    assert tester.get_midas_commission_rate(25_000_000.0) == 0.0002
    # 100M+: %0.01
    assert tester.get_midas_commission_rate(150_000_000.0) == 0.0001


def test_free_pyramiding_logic():
    pos = PositionState(
        symbol="F_THYAO",
        entry_price=300.0,
        initial_stop=290.0,
        trailing_stop=305.0,  # Breakeven üstünde
        lots=10,
        is_breakeven_activated=True
    )
    # 1.5R kârda piramitleme yapılamaz
    assert not pos.can_pyramid(1.5)
    # 2.2R kârda piramitleme yapılabilir
    assert pos.can_pyramid(2.2)

    # Piramitleme uygulanır
    new_lots = pos.add_pyramid(3)
    assert new_lots == 13
    assert pos.is_pyramided is True
    # İkinci kez piramitleme yapılamaz
    assert not pos.can_pyramid(3.0)


def test_rollover_and_calendar_spread():
    # Vade ayı olmayan tarih (Ocak 2026) -> NO_ROLL
    jan_date = datetime(2026, 1, 15)
    dec = ViopRollOverManager.evaluate_rollover("F_XU030", jan_date, near_price=11000.0)
    assert dec.should_roll is False
    assert dec.action == "NO_ROLL"

    # Vade sonuna 2 gün kala (Şubat 2026 sonu) -> ROLL_NOW
    feb_expiry = ViopRollOverManager.get_last_business_day_of_month(2026, 2)
    feb_near_expiry = datetime.combine(feb_expiry, datetime.min.time())
    dec_roll = ViopRollOverManager.evaluate_rollover("F_XU030", feb_near_expiry, near_price=11000.0)
    assert dec_roll.should_roll is True
    assert dec_roll.action == "ROLL_NOW"


def test_carry_arbitrage_engine():
    engine = CarryArbitrageEngine(benchmark_repo_rate=0.48)
    # Zımni faiz repo ile uyumlu -> ALE_REPO_HOLD
    sig_hold = engine.evaluate_carry(symbol="F_USDTRY", spot_price=36.0, futures_price=37.42, days_to_expiry=30)
    assert sig_hold.action == "ALE_REPO_HOLD"
    assert sig_hold.is_arbitrage_active is False

    # Fahiş Contango (Zımni faiz %65 >> %48) -> CASH_AND_CARRY
    sig_contango = engine.evaluate_carry(symbol="F_USDTRY", spot_price=36.0, futures_price=38.0, days_to_expiry=30)
    assert sig_contango.action == "CASH_AND_CARRY"
    assert sig_contango.is_arbitrage_active is True


def test_resample_bars_bist_session_alignment():
    # 1 günlük saatlik barlar
    timestamps = [
        datetime(2026, 3, 10, 10, 0),
        datetime(2026, 3, 10, 12, 0),
        datetime(2026, 3, 10, 14, 0),
        datetime(2026, 3, 10, 15, 0),
        datetime(2026, 3, 10, 17, 0)
    ]
    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": [100.0, 101.0, 102.0, 103.0, 104.0],
        "high": [102.0, 103.0, 104.0, 105.0, 106.0],
        "low": [99.0, 100.0, 101.0, 102.0, 103.0],
        "close": [101.0, 102.0, 103.0, 104.0, 105.0],
        "volume": [100, 200, 300, 400, 500]
    })
    resampled = EventDrivenBacktester.resample_bars(df, timeframe_minutes=240)
    # 2 bar üretilmeli: 14:15 ve 18:15
    assert len(resampled) == 2
    assert resampled["timestamp"].iloc[0].hour == 14 and resampled["timestamp"].iloc[0].minute == 15
    assert resampled["timestamp"].iloc[1].hour == 18 and resampled["timestamp"].iloc[1].minute == 15
