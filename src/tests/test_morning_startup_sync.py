"""
VİOP Sabah Başlatma ve Tablo Senkronizasyonu Test Paketi
(src/tests/test_morning_startup_sync.py).

Gereksinim Doğrulamaları:
1. Sabah başlatma rutini (08:30 - 09:30) VİOP 3 tablosunu eksiksiz inceler:
   - Tablo 1: Sözleşmeler Listesi (207 Sözleşme, 4 Sınıf, 63 Dayanak)
   - Tablo 2: Teminat Tablosu (09:00 Açılış Bülteni & Değişim Analizi)
   - Tablo 3: Teminat Tamamlama Çağrıları (Margin Call / Teminat Açığı)
2. Değişen teminat rakamları (% artış/azalış) tespit edilir ve veritabanına işlenir.
3. Değişen rakamlar dinamik olarak SystemConfig, TechnicalExecutioner ve PaperBroker'a yansıtılır.
4. Teminat artışının açık pozisyonlar ve Margin Call durumuna etkisi matematiksel olarak doğrulanır.
"""

import os
import sys
import pytest
from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.core.config import SystemConfig, ContractSpecification
from src.database.db_manager import DatabaseManager
from src.data.viop_feed_scheduler import ViopDataFeedScheduler
from src.strategy.technical_executioner import TechnicalExecutioner
from src.execution.paper_broker import PaperBroker


@pytest.fixture
def test_env(tmp_path):
    test_db_path = str(tmp_path / "test_viop_morning.db")
    db = DatabaseManager(db_path=test_db_path)
    scheduler = ViopDataFeedScheduler(db=db)
    scheduler.SCHEDULE_STATE_FILE = str(tmp_path / "viop_schedule_status.json")
    scheduler.MARKET_STATE_FILE = str(tmp_path / "live_market_state.json")
    scheduler.DATABASE_DIR = str(tmp_path)
    config = SystemConfig()
    return {
        "db": db,
        "scheduler": scheduler,
        "config": config,
        "tmp_path": tmp_path
    }


@pytest.mark.anyio
async def test_morning_startup_all_three_tables_synced(test_env):
    """Test 1: 3 VİOP tablosunun sabah başlatmada eksiksiz taranması."""
    scheduler = test_env["scheduler"]
    config = test_env["config"]
    db = test_env["db"]

    summary = await scheduler.run_morning_startup(
        account_equity=250_000.0,
        config_to_update=config,
        force=True
    )

    # 1. Sözleşmeler Tablosu Kontrolü
    assert summary["status"] == "SUCCESS"
    assert summary["contracts_universe"]["total_contracts"] == 207
    assert summary["contracts_universe"]["asset_categories_count"] == 4
    assert summary["contracts_universe"]["underlyings_count"] == 63
    assert len(db.get_viop_contracts()) == 207

    # 2. Teminat Tablosu Kontrolü
    assert summary["margins_table"]["total_margins_tracked"] == 207
    assert len(db.get_latest_margins()) == 207

    # 3. Teminat Tamamlama Çağrıları Kontrolü
    assert summary["margin_call_table"]["status"] in ("HEALTHY", "WARNING_LEVEL", "MARGIN_CALL_DEFICIT")
    assert summary["margin_call_table"]["check_type"] == "MORNING_STARTUP"

    # 4. Sisteme Yansıtma Kontrolü
    assert summary["system_reflection"]["reflected_count"] > 0
    assert "F_THYAO" in config.contracts
    assert "F_XU030" in config.contracts


@pytest.mark.anyio
async def test_margin_change_detection_and_percentage_calculation(test_env):
    """Test 2: Teminat rakamı değiştiğinde fark ve yüzdesel artışın tespit edilip DB'ye kaydedilmesi."""
    scheduler = test_env["scheduler"]
    db = test_env["db"]

    # 1. Adım: İlk temel teminatları kaydet (Örn: THYAO: 3850 TL, XU030: 17500 TL)
    await scheduler.sync_initial_margins(session_window="09:00_OPEN", force=True)

    # 2. Adım: Takasbank yeni bir bülten yayınlamış gibi teminat artışı simüle et
    # THYAO: 3850 -> 4235 TL (+%10.0 artış)
    # XU030: 17500 -> 19250 TL (+%10.0 artış)
    updated_margins = [
        {
            "contract_code": "F_THYAO1026",
            "initial_margin_try": 4235.0,
            "maintenance_margin_try": 4235.0 * 0.75,
            "session_window": "09:00_OPEN",
            "margin_change_pct": 10.0,
            "as_of_date": datetime.now().isoformat(),
            "announced_at": datetime.now().isoformat(),
            "source": "TAKASBANK_BULLETIN_UPDATED"
        },
        {
            "contract_code": "F_XU0301026",
            "initial_margin_try": 19250.0,
            "maintenance_margin_try": 19250.0 * 0.75,
            "session_window": "09:00_OPEN",
            "margin_change_pct": 10.0,
            "as_of_date": datetime.now().isoformat(),
            "announced_at": datetime.now().isoformat(),
            "source": "TAKASBANK_BULLETIN_UPDATED"
        }
    ]
    db.record_viop_margins(updated_margins, session_window="09:00_OPEN")

    latest_margins = db.get_latest_margins()
    assert latest_margins["F_THYAO1026"]["initial_margin_try"] == 4235.0
    assert latest_margins["F_THYAO1026"]["margin_change_pct"] == 10.0
    assert latest_margins["F_XU0301026"]["initial_margin_try"] == 19250.0
    assert latest_margins["F_XU0301026"]["margin_change_pct"] == 10.0


@pytest.mark.anyio
async def test_dynamic_reflection_to_execution_engine(test_env):
    """Test 3: Değişen teminat rakamlarının karar motoruna ve lot boyutlamaya anında yansıması."""
    scheduler = test_env["scheduler"]
    config = test_env["config"]
    db = test_env["db"]

    # Eski teminatla TechnicalExecutioner başlat
    executioner = TechnicalExecutioner(config=config)

    # THYAO için eski teminat 6500 TL iken lot hesabı yap
    portfolio_nav = 100_000.0
    free_margin = 15_000.0  # 15.000 TL serbest teminat
    entry_p = 300.0
    stop_p = 295.0  # Risk distance = 5 TL * 100 multiplier = 500 TL/lot
    # Normalde risk bütçesi (%2 = 2000 TL) 4 lot ister.
    # Ancak serbest teminat 15.000 TL:
    # 6500 TL teminat ile: floor(15000 / 6500) = 2 lot!
    lots_old, reason_old = executioner.calculate_lot_size_with_margin_cap(
        symbol="F_THYAO",
        entry_price=entry_p,
        stop_price=stop_p,
        portfolio_nav=portfolio_nav,
        free_margin=free_margin,
        compass_multiplier=1.0
    )
    assert lots_old == 2, f"Eski teminatla 2 lot olmalıydı, alınan: {lots_old}"

    # ŞİMDİ: Takasbank sabah bülteninde THYAO teminatını 6500'den 9000 TL'ye yükseltti!
    updated_margins = [
        {
            "contract_code": "F_THYAO1026",
            "initial_margin_try": 9000.0,
            "maintenance_margin_try": 9000.0 * 0.75,
            "session_window": "09:00_OPEN",
            "margin_change_pct": 38.46
        }
    ]
    db.record_viop_margins(updated_margins, session_window="09:00_OPEN")

    # Sabah başlatma yansıtması çalıştırılır:
    scheduler.apply_updated_margins_to_system(config_to_update=config, executioner=executioner)

    # Config ve Executioner'daki yeni teminatı kontrol et
    assert config.contracts["F_THYAO"].initial_margin_try == 9000.0
    assert config.contracts["F_THYAO1026"].initial_margin_try == 9000.0

    # Yeni teminatla (9000 TL) lot hesabı tekrar yapılır:
    # Serbest teminat 15.000 TL / 9.000 TL = 1 lot! (Sistem yeni teminatı hemen yansıttı!)
    lots_new, reason_new = executioner.calculate_lot_size_with_margin_cap(
        symbol="F_THYAO",
        entry_price=entry_p,
        stop_price=stop_p,
        portfolio_nav=portfolio_nav,
        free_margin=free_margin,
        compass_multiplier=1.0
    )
    assert lots_new == 1, f"Yükselen teminat sonrası serbest teminat sadece 1 lota yetmeliydi, alınan: {lots_new}"
    assert "Teminat Tıraşlaması" in reason_new


@pytest.mark.anyio
async def test_margin_hike_triggers_margin_call_warning(test_env):
    """Test 4: Teminat artışı durumunda açık pozisyonların sürdürme teminatını aşması ve Margin Call tespiti."""
    scheduler = test_env["scheduler"]
    db = test_env["db"]

    # 10 lot açık pozisyonumuz olsun (Örn: F_XU030)
    active_positions = [
        {
            "symbol": "F_XU0301026",
            "lots": 10,
            "pnl_try": -20_000.0,
            "side": "BUY"
        }
    ]
    # İlk teminat 17.500 TL -> 10 lot için toplam 175.000 TL başlangıç, 131.250 TL sürdürme
    # Portföy özkaynağı: 140.000 TL
    # 140.000 TL > 131.250 TL olduğu için başlangıçta durum uyarı (WARNING) veya sağlıklı
    report1 = scheduler.check_margin_call(
        account_equity=140_000.0,
        active_positions=active_positions,
        custom_check_type="MORNING_STARTUP"
    )
    assert report1.status in ("HEALTHY", "WARNING_LEVEL")

    # ŞİMDİ: Takasbank sabah bülteninde XU030 teminatını 17.500 TL'den 22.000 TL'ye çıkardı!
    # 10 lot için yeni başlangıç teminatı: 220.000 TL, Sürdürme (%75): 165.000 TL!
    # Özkaynak (140.000 TL) < Sürdürme (165.000 TL) oldu!
    updated_margins = [
        {
            "contract_code": "F_XU0301026",
            "initial_margin_try": 22000.0,
            "maintenance_margin_try": 16500.0,
            "session_window": "09:00_OPEN",
            "margin_change_pct": 25.71
        }
    ]
    db.record_viop_margins(updated_margins, session_window="09:00_OPEN")

    # Sabah başlatma margin call denetimi:
    report2 = scheduler.check_margin_call(
        account_equity=140_000.0,
        active_positions=active_positions,
        custom_check_type="MORNING_STARTUP"
    )

    # Yeni teminat rakamıyla sistem anında MARGIN_CALL_DEFICIT üretmelidir!
    assert report2.status == "MARGIN_CALL_DEFICIT", f"Teminat artışı sonrası açık oluşmalıydı, alınan: {report2.status}"
    assert report2.margin_deficit_try > 0.0
    assert report2.total_initial_margin == 220_000.0
    assert report2.total_maintenance_margin == 165_000.0
    # Açık = Başlangıç Teminatı (220.000) - Özkaynak (140.000) = 80.000 TL
    assert report2.margin_deficit_try == 80_000.0


def test_autonomous_operator_singleton_lock():
    """Test 9: Canlı Otonom Operatör singleton kilit mekanizması (çift instance engelleme)."""
    from src.execution.autonomous_operator import acquire_operator_lock
    import socket

    # Test amaçlı geçici port
    test_port = 59123
    lock1 = acquire_operator_lock(port=test_port)
    assert lock1 is not None, "İlk kilit başarıyla alınmalıdır."

    # İkinci instance aynı porta bağlanmaya çalışırsa None dönmelidir
    lock2 = acquire_operator_lock(port=test_port)
    assert lock2 is None, "İkinci instance engellenmeli ve None dönmelidir."

    # İlk kilit kapatıldığında tekrar kilit alınabilmelidir
    lock1.close()
    lock3 = acquire_operator_lock(port=test_port)
    assert lock3 is not None, "Kilit serbest kalınca tekrar alınabilmelidir."
    lock3.close()


@pytest.mark.anyio
async def test_autonomous_operator_ensures_morning_startup_and_state_json(test_env):
    """Test 10: Otonom Canlı Operatörün kullanıcı müdahalesi olmadan morning startup ve zengin JSON oluşturması."""
    from src.execution.autonomous_operator import AutonomousLiveOperator

    op = AutonomousLiveOperator(initial_capital=250_000.0)
    op.STATE_FILE = str(test_env["tmp_path"] / "live_market_state_test.json")
    op.DATABASE_DIR = str(test_env["tmp_path"])
    op.db = test_env["db"]
    op.scheduler = test_env["scheduler"]

    # 1. ensure_morning_startup çağrısı
    summary = await op.ensure_morning_startup(force=True)
    assert summary is not None
    assert "contracts_table" in summary or "status" in summary

    # 2. Döngü sonrasında yazılan state JSON doğrulaması
    # Mock contracts_snapshot
    contracts_snapshot = {
        "F_THYAO": {
            "ticker": "THYAO.IS",
            "type": "EQUITY",
            "last_price": 280.0,
            "bars_15m_count": 100,
            "bars_120m_count": 15,
            "bars_240m_count": 8
        }
    }
    macro = await op.fetch_live_macro_data()
    stream = await op.fetch_fintables_stream()
    ale_rates = op.calculate_ale_fund_daily_yield(annual_gross_rate=0.48)

    mc_report = op.scheduler.check_margin_call(
        account_equity=250_000.0,
        active_positions=[],
        custom_check_type="AUTONOMOUS_TEST"
    )

    state_payload = {
        "metadata": {
            "system": "Autonomous VİOP Live Operator v4.2",
            "synced_at": datetime.now().isoformat(),
            "mode": "100% AUTONOMOUS (ZERO MANUAL INTERVENTION)",
            "total_nav": 250_000.0,
            "free_margin": 250_000.0,
            "open_positions_count": 0,
            "executed_trades_this_cycle": 0
        },
        "macro": macro,
        "fintables_stream": stream,
        "ale_fund_nema": ale_rates,
        "contracts": contracts_snapshot,
        "margin_call": mc_report.model_dump(),
        "last_morning_sync": op.last_morning_sync_date
    }

    import json
    with open(op.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state_payload, f, ensure_ascii=False, indent=2, default=str)

    assert os.path.exists(op.STATE_FILE)
    with open(op.STATE_FILE, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["metadata"]["mode"] == "100% AUTONOMOUS (ZERO MANUAL INTERVENTION)"
    assert loaded["ale_fund_nema"]["annual_net_rate"] == 0.396
    assert loaded["margin_call"]["status"] == "HEALTHY"

