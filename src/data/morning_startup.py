"""
☀️ VİOP GÜNLÜK SABAH BAŞLATMA VE TABLO SENKRONİZASYON SERVİSİ
(src/data/morning_startup.py).

Gereksinimler:
1. Sistem her sabah başlarken Fintables.MCP yardımı ile VİOP sekmesi altındaki:
   - 1. Sözleşmeler Listesi (08:30)
   - 2. Teminat Tablosu (09:00 Açılış Bülteni)
   - 3. Teminat Tamamlama Çağrıları (Margin Call / Teminat Açığı)
   tablolarını inceler.
2. Değişen tüm rakamları (farklılaşan başlangıç/sürdürme teminatları, yeni/kapanan vadeler)
   tespit eder ve sisteme (Database, SystemConfig, Risk Motorları, Dashboard) anında yansıtır.
3. Canlı işlem öncesi tüm sistem parametrelerinin tutarlılığını onaylar.
"""

import asyncio
from datetime import datetime
import json
import logging
import os
import sys

# Proje ana dizinini sys.path'e ekle
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.core.config import SystemConfig
from src.database.db_manager import DatabaseManager
from src.data.viop_feed_scheduler import ViopDataFeedScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("MorningStartup")


async def run_morning_session_startup(
    account_equity: float = 150_000.0,
    force: bool = True
) -> dict:
    """
    Sabah seans açılışından önce VİOP 3 tablosunu senkronize eden ana fonksiyon.
    """
    db = DatabaseManager()
    scheduler = ViopDataFeedScheduler(db=db)
    config = SystemConfig()

    # Mevcut açık pozisyonları DB'den çek
    active_positions = db.get_active_positions()
    sys_state = db.get_latest_system_state()
    if sys_state and "total_nav" in sys_state:
        account_equity = float(sys_state["total_nav"])

    # 3 Tabloyu tara, değişen rakamları tespit et ve sisteme yansıt
    summary = await scheduler.run_morning_startup(
        account_equity=account_equity,
        active_positions=active_positions,
        config_to_update=config,
        force=force
    )

    return summary


def main():
    try:
        summary = asyncio.run(run_morning_session_startup())
        chg_count = summary.get("margins_table", {}).get("changed_margins_count", 0)
        mc_stat = summary.get("margin_call_table", {}).get("status", "HEALTHY")
        print(f"\n[SONUÇ] Sabah Başlatma Tamamlandı! Değişen Teminat: {chg_count} | Margin Call: {mc_stat}")
        sys.exit(0)
    except Exception as e:
        print(f"\n[HATA] Sabah başlatma sırasında kritik istisna: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

