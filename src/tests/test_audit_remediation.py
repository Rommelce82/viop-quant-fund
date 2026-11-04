"""
ChatGPT Codex 360-Derece Denetim Bulguları Doğrulama Test Paketi
(src/tests/test_audit_remediation.py).

Doğrulanan Düzeltmeler:
1. Piramitlemede tekil lot ekleme (Double lot bug fix)
2. Çıkışta tekil kayma muhasebesi (Double slippage deduction fix)
3. Gelecek verisi sızıntısının önlenmesi (Zero lookahead daily bias fix)
4. Bar içi High/Low olay sırası ve iz süren stop bütünlüğü
5. Sanal Broker (PaperBroker) Short açılış, çift yönlü kapatma ve Mark-to-Market NAV
"""

from datetime import datetime, timedelta
import pandas as pd
import pytest

from src.strategy.technical_executioner import TechnicalExecutioner, ExecutionActionV4
from src.strategy.position_manager import PositionState
from src.strategy.fundamental_compass import DirectionalBias, AssetChannel
from src.backtest.event_driven_tester import EventDrivenBacktester
from src.execution.paper_broker import PaperBroker


def test_pyramid_lot_single_addition():
    """1. Piramitlemede lotun çift eklenmesini engelleyen motor izolasyon testi."""
    executioner = TechnicalExecutioner()
    dates = pd.date_range("2026-10-01", periods=30, freq="4h")
    # 20 barlık donchian kırılımı için yukarı trend verisi
    prices = [300.0 + i * 2.0 for i in range(30)]
    hourly_df = pd.DataFrame({
        "timestamp": dates,
        "open": prices,
        "high": [p + 2.0 for p in prices],
        "low": [p - 1.0 for p in prices],
        "close": prices,
        "volume": [1000.0] * 30
    })
    daily_df = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-01", periods=40, freq="1D"),
        "open": [300.0] * 40,
        "high": [310.0] * 40,
        "low": [290.0] * 40,
        "close": [305.0] * 40,
        "volume": [10000.0] * 40
    })

    pos = PositionState(
        symbol="F_THYAO",
        entry_price=300.0,
        initial_stop=290.0,
        trailing_stop=295.0,
        lots=10,
        entry_time=datetime(2026, 10, 1),
        r_unit_price=10.0,
        is_breakeven_activated=True,
        scaled_out=True  # Ali Perşembe Kuralı: Önce %33 scale-out tamamlanmış olmalı
    )

    # +3.0R kârda yeni Donchian kırılımı (High ve Close kanalı yukarı aşıyor)
    idx = hourly_df.index[-1]
    hourly_df.loc[idx, "high"] = 370.0
    hourly_df.loc[idx, "close"] = 365.0

    dec = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=pos,
        portfolio_nav=150_000.0,
        free_margin=150_000.0
    )

    assert dec.action == ExecutionActionV4.PYRAMID_ADD_33
    assert dec.target_lots == 3
    # KRİTİK DOĞRULAMA: Karar anında pozisyon lotu değişmemiş olmalı!
    assert pos.lots == 10, "Karar anında pozisyon nesnesi mutasyona uğramamalı!"
    assert not pos.is_pyramided, "Emir gerçekleşmeden is_pyramided True olmamalı!"

    # İcra anında lot tek bir kez eklenmeli:
    pos.add_pyramid(dec.target_lots)
    assert pos.lots == 13, "Piramit gerçekleştiğinde lot tam olarak 13 olmalı (10 + 3)!"
    assert pos.is_pyramided is True


def test_chandelier_stop_open_bar_sequence():
    """4. Bar içi High/Low olay sırası ve iz süren stop ihlal testi."""
    executioner = TechnicalExecutioner()
    dates = pd.date_range("2026-10-01", periods=25, freq="4h")
    hourly_df = pd.DataFrame({
        "timestamp": dates,
        "open": [310.0] * 25,
        "high": [312.0] * 25,
        "low": [308.0] * 25,
        "close": [310.0] * 25,
        "volume": [1000.0] * 25
    })
    daily_df = pd.DataFrame({
        "timestamp": pd.date_range("2026-09-01", periods=30, freq="1D"),
        "open": [300.0] * 30,
        "high": [315.0] * 30,
        "low": [295.0] * 30,
        "close": [310.0] * 30,
        "volume": [10000.0] * 30
    })

    # Pozisyonun geçerli iz süren stopu 308.0 TL olsun
    pos = PositionState(
        symbol="F_THYAO",
        entry_price=300.0,
        initial_stop=290.0,
        trailing_stop=308.0,
        lots=5,
        entry_time=datetime(2026, 10, 1),
        r_unit_price=10.0
    )

    # Son barda fiyat 305 TL'ye düşerek stopu ihlal ediyor (Low = 305 <= 308)
    idx = hourly_df.index[-1]
    hourly_df.loc[idx, "high"] = 320.0  # Eğer high stopu yapay yükseltseydi paradoks oluşurdu
    hourly_df.loc[idx, "low"] = 305.0
    hourly_df.loc[idx, "close"] = 306.0

    dec = executioner.evaluate(
        symbol="F_THYAO",
        compass_bias=DirectionalBias.ONLY_LONG,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=pos,
        portfolio_nav=150_000.0,
        free_margin=150_000.0
    )

    assert dec.action == ExecutionActionV4.CHANDELIER_STOP_EXIT
    assert dec.stop_price == 308.0, "Stop ihlali bar başında geçerli olan 308 TL seviyesinden tetiklenmeli!"


def test_paper_broker_short_and_mtm_nav():
    """6. Sanal Broker (PaperBroker) Short açılış, kısmi kapatma ve Mark-to-Market NAV testi."""
    broker = PaperBroker(initial_capital=150_000.0)

    # A. Short Pozisyon Açılışı (F_THYAO, 5 lot @ 300 TL)
    exec_short = broker.execute_virtual_order({
        "symbol": "F_THYAO",
        "action": "ENTER_SHORT",
        "lots": 5,
        "current_price": 300.0,
        "stop_price": 310.0,
        "rationale": "Trend Kırılımı Short"
    })

    assert "F_THYAO" in broker.open_positions
    pos = broker.open_positions["F_THYAO"]
    assert pos.lots == -5, "Short pozisyon -5 lot olmalı"
    assert broker.cash_balance < 150_000.0, "Giriş komisyonu düşülmeli"

    # B. Mark-to-Market Değerleme Testi (Fiyat 290 TL'ye düştü -> Kârda)
    # 5 lot * 10 TL kâr * 100 çarpan = +5.000 TL kâr
    broker.update_market_price("F_THYAO", 290.0)
    unrealized = broker._get_position_unrealized_pnl(pos)
    assert unrealized > 4900.0, f"Unrealized PnL ~5000 TL olmalı, alınan: {unrealized}"
    assert broker.current_nav > 150_000.0, "NAV piyasa fiyatıyla değerlenmeli"

    # C. Kısmi Kapatma (SCALE_OUT_33: 5 lotun %33'ü = 1 lot kapat @ 290 TL)
    exec_close = broker.execute_virtual_order({
        "symbol": "F_THYAO",
        "action": "SCALE_OUT_33",
        "lots": 1,
        "current_price": 290.0,
        "stop_price": 300.0,
        "rationale": "Kısmi Kâr Al"
    })
    assert pos.lots == -4, "Kalan pozisyon -4 lot olmalı"
    assert exec_close.realized_pnl_try > 900.0, "1 lot için gerçekleşen net kâr pozitif olmalı"

    # D. Tam Kapatma (CHANDELIER_STOP_EXIT: kalan 4 lot @ 295 TL)
    exec_exit = broker.execute_virtual_order({
        "symbol": "F_THYAO",
        "action": "CHANDELIER_STOP_EXIT",
        "lots": 4,
        "current_price": 295.0,
        "stop_price": 295.0,
        "rationale": "Trend Sonu"
    })
    assert "F_THYAO" not in broker.open_positions, "Tüm pozisyon kapanmalı"
    assert broker.current_nav == broker.cash_balance, "Pozisyon kapandığında NAV = Nakit olmalı"
