"""
Ali Perşembe 33 Kural, Portföy Yönetimi ve Veritabanı Doğrulama Testi.
(test_ali_persembe_33_rules.py)
"""

from datetime import datetime, date
import os
import pandas as pd
import pytest

from src.database.db_manager import DatabaseManager
from src.strategy.portfolio_manager import (
    PendingLimitOrder,
    PortfolioRiskManager,
    TradingMode,
    SECTOR_MAP
)
from src.strategy.fundamental_compass import DirectionalBias
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalExecutioner
)
from src.tests.test_v4_architecture import create_mock_market_data


def test_ali_persembe_microstructure_filters():
    """BÖLÜM 1: 33 Kural Mikro-Yapı ve İndikatör Testleri."""
    executioner = TechnicalExecutioner()
    daily_df, hourly_df = create_mock_market_data()

    # 1. KAP Haberi Filtresi
    dec_kap = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0,
        has_kap_news=True
    )
    assert dec_kap.action == ExecutionActionV4.REJECT_KAP_NEWS

    # 2. Saat 09:30-10:30 Açılış Çalkantısı Filtresi
    dec_time = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0,
        current_time_override=datetime(2026, 10, 15, 10, 15)
    )
    assert dec_time.action == ExecutionActionV4.REJECT_TIME_OPENING

    # 3. Gap > %2 Filtresi
    hourly_gap = hourly_df.copy()
    hourly_gap.loc[hourly_gap.index[-1], "open"] = hourly_gap.loc[hourly_gap.index[-2], "close"] * 1.03  # %3 gap
    dec_gap = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_gap,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0,
        current_time_override=datetime(2026, 10, 15, 14, 0)
    )
    assert dec_gap.action == ExecutionActionV4.REJECT_GAP_LARGE

    # 4. Üst Fitil (Wick) > %40 Filtresi
    hourly_wick = hourly_df.copy()
    idx = hourly_wick.index[-1]
    hourly_wick.loc[idx, "high"] = 330.0
    hourly_wick.loc[idx, "close"] = 315.0
    hourly_wick.loc[idx, "open"] = 312.0
    hourly_wick.loc[idx, "low"] = 310.0
    # Range = 20, Wick = 330 - 315 = 15 -> 15/20 = %75 > %40
    dec_wick = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_wick,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0,
        current_time_override=datetime(2026, 10, 15, 14, 0)
    )
    assert dec_wick.action == ExecutionActionV4.REJECT_WICK_EXCESSIVE

    # 5. Inside Bar Filtresi (Üst fitil %40'ın altında, tamamen önceki barın içinde)
    hourly_ib = hourly_df.copy()
    idx = hourly_ib.index[-1]
    prev = hourly_ib.index[-2]
    prev_high = hourly_ib.loc[prev, "high"]
    prev_low = hourly_ib.loc[prev, "low"]
    hourly_ib.loc[idx, "open"] = prev_low + 1.0
    hourly_ib.loc[idx, "close"] = prev_high - 0.2  # Kapanış tepeye yakın, fitil %5 civarı
    hourly_ib.loc[idx, "high"] = prev_high - 0.1
    hourly_ib.loc[idx, "low"] = prev_low + 0.5
    dec_ib = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_ib,
        position_state=None,
        portfolio_nav=1_000_000.0,
        free_margin=1_000_000.0,
        current_time_override=datetime(2026, 10, 15, 14, 0)
    )
    assert dec_ib.action == ExecutionActionV4.REJECT_INSIDE_BAR


def test_portfolio_risk_manager_rules():
    """BÖLÜM 1 & 2: Risk Yönetimi, Anti-Martingale, Whipsaw, Sektör Haritası ve Kâr Eğrisi."""
    pm = PortfolioRiskManager(initial_capital=1_000_000.0)

    # 1. Sektör ve Portföy Kapasite Sınırı (Otonom Mod: İnsan kısıtları kaldırıldı, serbest teminat & kapasite yönetir)
    assert SECTOR_MAP["F_AKBNK"] == "BANKA"
    assert SECTOR_MAP["F_THYAO"] == "HAVACILIK"

    pm.state.active_positions["F_AKBNK"] = {"lots": 10}
    pm.state.active_positions["F_GARAN"] = {"lots": 10}
    ok_bank, msg_bank = pm.check_sector_correlation("F_ISCTR")  # Otonom modda fırsat engellenmez
    assert ok_bank, "Otonom modda aynı sektördeki fırsatlar engellenmemelidir!"

    # Kapasite tavanı (MAX_TOTAL_POSITIONS = 100)
    for i in range(100):
        pm.state.active_positions[f"F_SYM_{i}"] = {"lots": 1}
    ok_full, msg_full = pm.check_sector_correlation("F_THYAO")
    assert not ok_full, "Kapasite tavanı aşıldığında yeni pozisyona izin verilmemelidir!"
    pm.state.active_positions.clear()

    # 2. Anti-Martingale (Üst üste 4 stop -> Risk %1)
    assert pm.get_risk_budget_pct() == 0.02
    for _ in range(4):
        pm.record_trade_result(pnl=-5000.0, symbol="F_THYAO", side="LONG")
    assert pm.get_risk_budget_pct() == 0.01, "4 stop sonrası risk bütçesi %1 olmalı!"

    # 3. Whipsaw Kalkanı (Aynı gün Long ve Short stop olunursa kilit)
    pm.update_day_boundary(datetime(2026, 10, 15, 9, 30), 1_000_000.0)
    pm.record_trade_result(pnl=-2000.0, symbol="F_AKBNK", side="LONG")
    locked_1, _ = pm.is_whipsaw_locked("F_AKBNK")
    assert not locked_1

    pm.record_trade_result(pnl=-2000.0, symbol="F_AKBNK", side="SHORT")
    locked_2, msg_whip = pm.is_whipsaw_locked("F_AKBNK")
    assert locked_2, "Aynı gün Long ve Short stop olunca kilitlenmelidir!"

    # 4. Devre Kesici (Circuit Breaker: Günlük NAV -%4)
    pm.state.current_nav = 955_000.0  # -%4.5 düşüş
    cb_active, msg_cb = pm.check_circuit_breaker()
    assert cb_active, "Günlük NAV -%4 olunca devre kesici tetiklenmelidir!"

    # 5. Limit Emir Zaman Aşımı (Cancel-on-Bar-Close)
    t1 = datetime(2026, 10, 15, 10, 0)
    t2 = datetime(2026, 10, 15, 11, 0)
    pm.state.pending_orders["ORD_1"] = PendingLimitOrder(
        order_id="ORD_1", symbol="F_THYAO", side="LONG", price=310.0, lots=5, created_bar_time=t1
    )
    cancelled = pm.cancel_expired_limit_orders(current_bar_time=t2)
    assert "ORD_1" in cancelled, "Bar kapanışında gerçekleşmemiş limit emir iptal edilmelidir!"

    # 6. Kâr Eğrisi (Equity Curve) ve Otonom Mod Geçişi (LIVE vs PAPER_TRADE)
    # 20 periyot boyunca 1M'de giden eğri, aniden 900k'ya düşerse SMA20 altına iner
    for _ in range(25):
        pm.update_day_boundary(datetime.now(), 1_000_000.0)
    assert pm.state.trading_mode == TradingMode.LIVE_TRADING

    pm.update_day_boundary(datetime.now(), 900_000.0)
    assert pm.state.trading_mode == TradingMode.PAPER_TRADE, "NAV < SMA20 olunca PAPER_TRADE moduna geçmeli!"

    for _ in range(25):
        pm.update_day_boundary(datetime.now(), 1_100_000.0)
    assert pm.state.trading_mode == TradingMode.LIVE_TRADING, "Sanal NAV > SMA20 olunca LIVE moduna dönmeli!"


def test_sqlite_database_manager():
    """BÖLÜM 2 & 3: SQLite Veritabanı ve Dashboard Entegrasyonu."""
    test_db = "test_viop.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    db = DatabaseManager(db_path=test_db)

    # 1. Sistem Durumu Kaydet
    db.record_system_state(
        total_nav=1_050_000.0,
        free_margin=850_000.0,
        daily_pnl=50_000.0,
        daily_return_pct=5.0,
        trading_mode="LIVE_TRADING",
        consecutive_losses=0,
        circuit_breaker_active=False
    )
    latest = db.get_latest_system_state()
    assert latest is not None
    assert latest["total_nav"] == 1_050_000.0
    assert latest["trading_mode"] == "LIVE_TRADING"

    # 2. Açık Pozisyon Senkronizasyonu
    db.sync_active_positions([{
        "symbol": "F_THYAO",
        "side": "LONG",
        "lots": 15,
        "entry_price": 312.5,
        "current_price": 318.0,
        "initial_stop": 305.0,
        "trailing_stop": 312.5,
        "pnl_try": 8250.0,
        "r_multiple": 0.73,
        "bars_held": 4,
        "entry_time": datetime.now().isoformat()
    }])
    positions = db.get_active_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "F_THYAO"

    # 3. Kâr Eğrisi
    db.record_equity_point(nav=1_050_000.0, sma20=1_000_000.0, mode="LIVE_TRADING")
    eq_df = db.get_equity_curve_df()
    assert len(eq_df) == 1
    assert eq_df["nav"].iloc[0] == 1_050_000.0

    # Temizlik
    try:
        if os.path.exists(test_db):
            os.remove(test_db)
    except Exception:
        pass
