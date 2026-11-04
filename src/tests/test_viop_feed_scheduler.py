"""
Fintables VİOP Veri Güncelleme Takvimi Test Paketi (test_viop_feed_scheduler.py).

Gereksinimler:
1. Sözleşmeler Listesi: Günde 1 Kez (Sabah 08:30)
2. Teminat Tutarları (Initial Margin): Günde 2 Kez (09:00 ve 14:00)
3. Fiyat & İndikatör Barları: 15 Dakikada 1 (240m Resampler)
4. Margin Call / Hesaba Ait Teminat: 15 Dk Pasif + Bar Kapanışları (14:15 & 18:15)
5. ALE Fonu Net Nema Hesabı: Seans Sonu (18:15)
"""

from datetime import datetime, time
import os
import sys
import pytest
import pandas as pd

# Proje kök dizini
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.data.viop_feed_scheduler import ViopDataFeedScheduler
from src.database.db_manager import DatabaseManager


@pytest.fixture
def scheduler(tmp_path):
    test_db_path = str(tmp_path / "test_viop.db")
    db = DatabaseManager(db_path=test_db_path)
    sched = ViopDataFeedScheduler(db=db)
    sched.SCHEDULE_STATE_FILE = str(tmp_path / "viop_schedule_status.json")
    return sched


@pytest.mark.anyio
async def test_contracts_universe_0830(scheduler):
    """1. Sözleşmeler Listesi (Sabah 08:30) Testi."""
    contracts = await scheduler.sync_contracts_universe(force=True)
    assert len(contracts) == 207, f"207 VİOP sözleşmesi dönmelidir, alınan: {len(contracts)}"
    
    # 4 Ana Varlık sınıfı kontrolü (Fintables AI 26 Ekim 2026 Standartları)
    categories = {c["asset_category"] for c in contracts}
    assert len(categories) == 4
    assert "EQUITY" in categories
    assert "INDEX" in categories
    assert "COMMODITY" in categories
    assert "FX" in categories

    # Veritabanı teyidi
    db_contracts = scheduler.db.get_viop_contracts()
    assert len(db_contracts) == 207
    assert scheduler.last_syncs["contracts_universe_0830"] is not None


@pytest.mark.anyio
async def test_initial_margins_0900_and_1400(scheduler):
    """2. Teminat Tutarları (09:00 ve 14:00) Testi."""
    # 09:00 Açılış Bülteni
    margins_0900 = await scheduler.sync_initial_margins(session_window="09:00_OPEN", force=True)
    assert len(margins_0900) == 207
    assert margins_0900[0]["session_window"] == "09:00_OPEN"
    assert margins_0900[0]["initial_margin_try"] > 0
    assert margins_0900[0]["maintenance_margin_try"] == margins_0900[0]["initial_margin_try"] * 0.75

    # 14:00 Gün Ortası Bülteni
    margins_1400 = await scheduler.sync_initial_margins(session_window="14:00_MIDDAY", force=True)
    assert len(margins_1400) == 207
    assert margins_1400[0]["session_window"] == "14:00_MIDDAY"

    # DB Teyidi
    latest = scheduler.db.get_latest_margins()
    assert len(latest) == 207


def test_240m_resampler(scheduler):
    """3. Fiyat & İndikatör Barları (15 Dakikada 1 - 240m Resampler) Mantık Testi."""
    # 16 adet 15 dakikalık bar (4 saatlik zaman dilimi)
    timestamps = pd.date_range("2026-10-26 09:30", periods=16, freq="15min")
    df_15m = pd.DataFrame({
        "timestamp": timestamps,
        "open": [100.0 + i for i in range(16)],
        "high": [105.0 + i for i in range(16)],
        "low": [98.0 + i for i in range(16)],
        "close": [102.0 + i for i in range(16)],
        "volume": [1000.0 for _ in range(16)]
    })

    df_240m = scheduler.resample_to_240m(df_15m)
    assert not df_240m.empty, "240m resample boş olmamalı"
    assert df_240m.iloc[0]["open"] == 100.0
    assert max(df_240m["high"]) == max(df_15m["high"])
    assert min(df_240m["low"]) == min(df_15m["low"])
    assert df_240m.iloc[0]["low"] == min(df_15m["low"])


def test_margin_call_passive_and_bar_close(scheduler):
    """4. Margin Call / Hesaba Ait Teminat (15 Dk Pasif + Bar Kapanışları) Testi."""
    # İlk teminatları yükle
    scheduler.db.record_viop_contracts([
        {
            "contract_code": "F_THYAO1026",
            "underlying_symbol": "THYAO",
            "asset_category": "EQUITY",
            "contract_size": 100.0,
            "expiry_month": 10,
            "expiry_year": 2026,
            "initial_margin_try": 3850.0,
            "maintenance_margin_try": 2887.5,
            "is_active": True
        }
    ])
    scheduler.db.record_viop_margins([
        {
            "contract_code": "F_THYAO1026",
            "initial_margin_try": 3850.0,
            "maintenance_margin_try": 2887.5,
            "session_window": "09:00_OPEN",
            "margin_change_pct": 0.0
        }
    ])

    positions = [{"symbol": "F_THYAO1026", "lots": 5, "pnl_try": -1000.0}]

    # A. Sağlıklı Hesap (Özkaynak = 150.000 TL)
    report_healthy = scheduler.check_margin_call(
        account_equity=150000.0,
        active_positions=positions,
        custom_check_type="PASSIVE_15M"
    )
    assert report_healthy.status == "HEALTHY"
    assert report_healthy.margin_deficit_try == 0.0
    assert not report_healthy.liquidation_required

    # B. Teminat Açığı Olan Hesap (Özkaynak < Sürdürme Teminatı)
    # 5 lot * 3850 = 19250 TL Başlangıç, Sürdürme = 14437.5 TL
    # Eğer özkaynak 10000 TL ise -> Sürdürme teminatının altında!
    report_deficit = scheduler.check_margin_call(
        account_equity=10000.0,
        active_positions=positions,
        custom_check_type="BAR_CLOSE_1415"
    )
    assert report_deficit.status == "MARGIN_CALL_DEFICIT"
    assert report_deficit.margin_deficit_try == (19250.0 - 10000.0) # 9250 TL açık
    assert report_deficit.liquidation_required is True
    assert report_deficit.target_liquidation_symbol == "F_THYAO1026"


def test_ale_fund_eod_1815(scheduler):
    """5. ALE Fonu Net Nema Hesabı (Seans Sonu 18:15) Testi."""
    idle_cash = 100000.0
    report = scheduler.calculate_ale_fund_eod(idle_cash=idle_cash, annual_gross_rate=0.48, force=True)

    expected_gross = 100000.0 * (0.48 / 365.0)
    expected_tax = expected_gross * 0.175
    expected_net = expected_gross - expected_tax

    assert abs(report.daily_gross_yield_try - round(expected_gross, 2)) <= 0.05
    assert abs(report.withholding_tax_try - round(expected_tax, 2)) <= 0.05
    assert abs(report.daily_net_yield_try - round(expected_net, 2)) <= 0.05
    assert report.cumulative_ale_vault_try == report.daily_net_yield_try

    # İkinci gün kümülatif kasa birikim testi
    report_day2 = scheduler.calculate_ale_fund_eod(idle_cash=idle_cash, annual_gross_rate=0.48, force=True)
    assert report_day2.cumulative_ale_vault_try > report.cumulative_ale_vault_try
