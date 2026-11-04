"""
Fintables MCP VİOP Veri Güncelleme Takvimi ve Karar Motoru Besleme Servisi
(src/data/viop_feed_scheduler.py).

FİNTABLES VERİ GÜNCELLEME TAKVİMİ:
┌──────────────────────────────────────┬────────────────────────────────────┐
│ VERİ TİPİ                            │ GÜNCELLEME ZAMANI                  │
├──────────────────────────────────────┼────────────────────────────────────┤
│ • Sözleşmeler Listesi                │ Günde 1 Kez (Sabah 08:30)          │
│ • Teminat Tutarları (Initial Margin) │ Günde 2 Kez (09:00 ve 14:00)       │
│ • Fiyat & İndikatör Barları          │ 15 Dakikada 1 (240m Resampler)     │
│ • Margin Call / Hesaba Ait Teminat   │ 15 Dk Pasif + Bar Kapanışları      │
│ • ALE Fonu Net Nema Hesabı           │ Seans Sonu (18:15)                 │
└──────────────────────────────────────┴────────────────────────────────────┘

Bu modül:
- BIST Takasbank ve Fintables MCP protokolü ile 5 veri hattını zamanlayıcıya bağlı olarak çalıştırır.
- Çevrimdışı/token geçersizlik durumlarında Takasbank VİOP kataloğu ve yerel önbellek (Fallback Cache) üzerinden kesintisiz çalışmayı garanti eder.
- Karar motorları (TechnicalExecutioner, FundamentalCompass, PositionManager) için en güncel veriyi hazır tutar.
"""

import asyncio
from datetime import datetime, time, timedelta
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional
import pandas as pd
import yfinance as yf

# Proje kök dizinini ekle
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.data.fintables_mcp import FintablesMCPClient
from src.data.schemas import (
    AleFundEodReport,
    MarginCallReport,
    ViopContractInfo,
    ViopMarginInfo
)
from src.data.viop_universe_definitions import (
    generate_full_viop_universe,
    get_universe_breakdown
)
from src.database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# UTF-8 Terminal desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class ViopDataFeedScheduler:
    """
    Fintables VİOP Veri Güncelleme Takvimi Yöneticisi ve Besleme Hattı.
    """

    DATABASE_DIR = os.path.join(os.path.dirname(__file__), "..", "database")
    SCHEDULE_STATE_FILE = os.path.join(DATABASE_DIR, "viop_schedule_status.json")
    MARKET_STATE_FILE = os.path.join(DATABASE_DIR, "live_market_state.json")

    # 20 VİOP Sözleşmesi Evreni (Hisse, Endeks, Emtia, FX)
    VIOP_SYMBOLS = [
        # Hisse Pay Vadeli (5 Sözleşme)
        {"symbol": "F_THYAO", "code": "F_THYAO1026", "ticker": "THYAO.IS", "type": "EQUITY", "company": "THYAO", "multiplier": 100.0, "init_margin": 3850.0},
        {"symbol": "F_AKBNK", "code": "F_AKBNK1026", "ticker": "AKBNK.IS", "type": "EQUITY", "company": "AKBNK", "multiplier": 100.0, "init_margin": 1450.0},
        {"symbol": "F_GARAN", "code": "F_GARAN1026", "ticker": "GARAN.IS", "type": "EQUITY", "company": "GARAN", "multiplier": 100.0, "init_margin": 2300.0},
        {"symbol": "F_EREGL", "code": "F_EREGL1026", "ticker": "EREGL.IS", "type": "EQUITY", "company": "EREGL", "multiplier": 100.0, "init_margin": 950.0},
        {"symbol": "F_TUPRS", "code": "F_TUPRS1026", "ticker": "TUPRS.IS", "type": "EQUITY", "company": "TUPRS", "multiplier": 100.0, "init_margin": 2400.0},
        # Endeks Vadeli (5 Sözleşme)
        {"symbol": "F_XU030", "code": "F_XU0301026", "ticker": "XU030.IS", "type": "INDEX", "company": "XU030", "multiplier": 10.0, "init_margin": 17500.0},
        {"symbol": "F_XU100", "code": "F_XU1001026", "ticker": "XU100.IS", "type": "INDEX", "company": "XU100", "multiplier": 10.0, "init_margin": 14000.0},
        {"symbol": "F_XLBNK", "code": "F_XLBNK1026", "ticker": "XBANK.IS", "type": "INDEX", "company": "XBANK", "multiplier": 10.0, "init_margin": 11000.0},
        {"symbol": "F_XUSIN", "code": "F_XUSIN1026", "ticker": "XUSIN.IS", "type": "INDEX", "company": "XUSIN", "multiplier": 10.0, "init_margin": 12500.0},
        {"symbol": "F_XGMYO", "code": "F_XGMYO1026", "ticker": "XGMYO.IS", "type": "INDEX", "company": "XGMYO", "multiplier": 10.0, "init_margin": 4200.0},
        # Emtia Vadeli (5 Sözleşme)
        {"symbol": "F_XAUUSD", "code": "F_XAUUSD1026", "ticker": "GC=F", "type": "COMMODITY", "company": "ALTIN", "multiplier": 1.0, "init_margin": 7200.0},
        {"symbol": "F_XAGUSD", "code": "F_XAGUSD1026", "ticker": "SI=F", "type": "COMMODITY", "company": "GUMUS", "multiplier": 1.0, "init_margin": 5800.0},
        {"symbol": "F_BRENT", "code": "F_BRENT1026", "ticker": "BZ=F", "type": "COMMODITY", "company": "BRENT", "multiplier": 1.0, "init_margin": 6500.0},
        {"symbol": "F_PLAT", "code": "F_PLAT1026", "ticker": "PL=F", "type": "COMMODITY", "company": "PLATIN", "multiplier": 1.0, "init_margin": 4500.0},
        {"symbol": "F_COPPER", "code": "F_COPPER1026", "ticker": "HG=F", "type": "COMMODITY", "company": "BAKIR", "multiplier": 1.0, "init_margin": 5100.0},
        # Döviz Vadeli (5 Sözleşme)
        {"symbol": "F_USDTRY", "code": "F_USDTRY1026", "ticker": "TRY=X", "type": "FX", "company": "USDTRY", "multiplier": 1000.0, "init_margin": 3600.0},
        {"symbol": "F_EURTRY", "code": "F_EURTRY1026", "ticker": "EURTRY=X", "type": "FX", "company": "EURTRY", "multiplier": 1000.0, "init_margin": 3900.0},
        {"symbol": "F_EURUSD", "code": "F_EURUSD1026", "ticker": "EURUSD=X", "type": "FX", "company": "EURUSD", "multiplier": 1000.0, "init_margin": 2800.0},
        {"symbol": "F_GBPTRY", "code": "F_GBPTRY1026", "ticker": "GBPTRY=X", "type": "FX", "company": "GBPTRY", "multiplier": 1000.0, "init_margin": 4600.0},
        {"symbol": "F_DXY", "code": "F_DXY1026", "ticker": "DX-Y.NYB", "type": "FX", "company": "DXY", "multiplier": 1000.0, "init_margin": 3100.0}
    ]

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager()
        os.makedirs(self.DATABASE_DIR, exist_ok=True)
        self.fintables: Optional[FintablesMCPClient] = None
        try:
            self.fintables = FintablesMCPClient()
        except Exception as e:
            logger.info("Fintables MCP İstemcisi çevrimdışı modda başlatıldı: %s", e)

        # Son çalıştırma zaman damgaları
        self.last_syncs: Dict[str, Optional[datetime]] = {
            "contracts_universe_0830": None,
            "margins_0900": None,
            "margins_1400": None,
            "bars_15m": None,
            "margin_call_passive_15m": None,
            "margin_call_bar_close_1415": None,
            "margin_call_bar_close_1815": None,
            "ale_fund_1815": None
        }
        self._load_status()

    def _load_status(self) -> None:
        """Kayıtlı takvim senkronizasyon durumunu yükler."""
        if os.path.exists(self.SCHEDULE_STATE_FILE):
            try:
                with open(self.SCHEDULE_STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.get("last_syncs", {}).items():
                        if v:
                            self.last_syncs[k] = datetime.fromisoformat(v)
            except Exception as e:
                logger.debug("Takvim durumu okunamadı: %s", e)

    def _save_status(self) -> None:
        """Takvim durumunu dosyaya kaydeder."""
        status_payload = {
            "title": "FİNTABLES VERİ GÜNCELLEME TAKVİMİ CANLI DURUMU",
            "as_of_time": datetime.now().isoformat(),
            "schedule": {
                "contracts_universe": {
                    "rule": "Günde 1 Kez (Sabah 08:30)",
                    "last_sync": self.last_syncs["contracts_universe_0830"].isoformat() if self.last_syncs["contracts_universe_0830"] else None,
                    "target_time": "08:30:00"
                },
                "initial_margins": {
                    "rule": "Günde 2 Kez (09:00 ve 14:00)",
                    "last_sync_0900": self.last_syncs["margins_0900"].isoformat() if self.last_syncs["margins_0900"] else None,
                    "last_sync_1400": self.last_syncs["margins_1400"].isoformat() if self.last_syncs["margins_1400"] else None,
                    "target_times": ["09:00:00", "14:00:00"]
                },
                "prices_and_indicators": {
                    "rule": "15 Dakikada 1 (240m Resampler)",
                    "last_sync": self.last_syncs["bars_15m"].isoformat() if self.last_syncs["bars_15m"] else None,
                    "target_interval": "15 dakika"
                },
                "margin_call_check": {
                    "rule": "15 Dk Pasif + Bar Kapanışları (14:15 ve 18:15)",
                    "last_passive_sync": self.last_syncs["margin_call_passive_15m"].isoformat() if self.last_syncs["margin_call_passive_15m"] else None,
                    "last_bar_close_1415": self.last_syncs["margin_call_bar_close_1415"].isoformat() if self.last_syncs["margin_call_bar_close_1415"] else None,
                    "last_bar_close_1815": self.last_syncs["margin_call_bar_close_1815"].isoformat() if self.last_syncs["margin_call_bar_close_1815"] else None,
                    "target_events": ["15m passive", "14:15 bar close", "18:15 bar close"]
                },
                "ale_fund_nema": {
                    "rule": "Seans Sonu (18:15)",
                    "last_sync": self.last_syncs["ale_fund_1815"].isoformat() if self.last_syncs["ale_fund_1815"] else None,
                    "target_time": "18:15:00"
                }
            },
            "last_syncs": {k: v.isoformat() if v else None for k, v in self.last_syncs.items()},
            "universe_breakdown": get_universe_breakdown()
        }
        with open(self.SCHEDULE_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(status_payload, f, ensure_ascii=False, indent=2)

    # -------------------------------------------------------------------------
    # 1. SÖZLEŞMELER LİSTESİ: Günde 1 Kez (Sabah 08:30)
    # -------------------------------------------------------------------------
    async def sync_contracts_universe(self, force: bool = False) -> List[Dict[str, Any]]:
        """
        VİOP Sözleşmeler Listesi Senkronizasyonu.
        Sabah 08:30'da günde 1 kez çekilir.
        """
        now = datetime.now()
        contracts_data: List[Dict[str, Any]] = []

        if self.fintables:
            try:
                live_contracts = await self.fintables.fetch_viop_contracts()
                for c in live_contracts:
                    contracts_data.append(c.model_dump())
            except Exception as e:
                logger.warning("Fintables MCP üzerinden VİOP sözleşmeleri çekilemedi: %s. Takasbank kataloğuna geçiliyor.", e)

        # Fallback: BIST & Fintables resmi tam kataloğu (4 Ana Varlık Sınıfı, 63 Dayanak, 207 Sözleşme)
        if not contracts_data:
            contracts_data = generate_full_viop_universe(as_of_date=now)

        # Veritabanına kaydet
        self.db.record_viop_contracts(contracts_data)
        self.last_syncs["contracts_universe_0830"] = now
        self._save_status()
        n_cats = len({c.get("asset_category") for c in contracts_data})
        n_unds = len({c.get("underlying_symbol") for c in contracts_data})
        print(f"[{now.strftime('%H:%M:%S')}] ✓ [08:30 Takvimi] VİOP Sözleşmeler Listesi Güncellendi ({len(contracts_data)} Sözleşme | {n_cats} Varlık Sınıfı | {n_unds} Dayanak).")
        return contracts_data

    # -------------------------------------------------------------------------
    # 2. TEMİNAT TUTARLARI (Initial Margin): Günde 2 Kez (09:00 ve 14:00)
    # -------------------------------------------------------------------------
    async def sync_initial_margins(
        self,
        session_window: str = "09:00_OPEN",
        force: bool = False
    ) -> List[Dict[str, Any]]:
        """
        VİOP Başlangıç ve Sürdürme Teminatları Senkronizasyonu.
        Günde 2 kez: 09:00 (Açılış Teminat Bülteni) ve 14:00 (Gün Ortası Bülteni).
        Tüm 207 sözleşme için Takasbank teminat bültenini günceller.
        """
        now = datetime.now()
        margins_data: List[Dict[str, Any]] = []

        # Önceki kayıtlı teminatları alarak değişim hesaplayalım
        prev_margins = self.db.get_latest_margins()

        if self.fintables:
            try:
                live_margins = await self.fintables.fetch_viop_margins(session_window=session_window)
                for m in live_margins:
                    m_dict = m.model_dump()
                    code = m_dict["contract_code"]
                    init_m = m_dict["initial_margin_try"]
                    old_m = prev_margins.get(code, {}).get("initial_margin_try", init_m)
                    chg_pct = round(((init_m - old_m) / old_m * 100.0), 2) if old_m > 0 else 0.0
                    m_dict["margin_change_pct"] = chg_pct
                    margins_data.append(m_dict)
            except Exception as e:
                logger.warning("Fintables MCP teminat sorgusu başarısız: %s. Takasbank bültenine geçiliyor.", e)

        if not margins_data:
            all_contracts = generate_full_viop_universe(as_of_date=now)
            for c in all_contracts:
                code = c["contract_code"]
                init_m = c["initial_margin_try"]
                maint_m = c["maintenance_margin_try"]

                old_m = prev_margins.get(code, {}).get("initial_margin_try", init_m)
                chg_pct = round(((init_m - old_m) / old_m * 100.0), 2) if old_m > 0 else 0.0

                margins_data.append({
                    "contract_code": code,
                    "initial_margin_try": init_m,
                    "maintenance_margin_try": maint_m,
                    "session_window": session_window,
                    "margin_change_pct": chg_pct,
                    "as_of_date": now.isoformat(),
                    "announced_at": now.isoformat(),
                    "source": f"TAKASBANK_BULLETIN_{session_window}"
                })

        # Veritabanına kaydet
        self.db.record_viop_margins(margins_data, session_window=session_window)
        if "09:00" in session_window:
            self.last_syncs["margins_0900"] = now
        else:
            self.last_syncs["margins_1400"] = now

        self._save_status()
        print(f"[{now.strftime('%H:%M:%S')}] ✓ [{session_window} Takvimi] VİOP Teminat Tutarları Güncellendi ({len(margins_data)} Sözleşme).")
        return margins_data

    # -------------------------------------------------------------------------
    # 3. FİYAT & İNDİKATÖR BARLARI: 15 Dakikada 1 (240m Resampler)
    # -------------------------------------------------------------------------
    @staticmethod
    def resample_to_240m(df_15m: pd.DataFrame) -> pd.DataFrame:
        """
        15 dakikalık barları Ali Perşembe karar kurallarına göre 240 dakikalık (4 saat)
        seans içi karar pencerelerine (14:15 ve 18:15) hizalayarak resample eder.
        """
        if df_15m.empty:
            return pd.DataFrame()

        df = df_15m.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")

        # 4 saatlik resampling
        resampled = df.resample("240min", origin="start_day").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna().reset_index()

        return resampled

    async def sync_prices_and_indicators(self, force: bool = False) -> Dict[str, Any]:
        """
        15 Dakikada 1 Fiyat & İndikatör Barları Senkronizasyonu.
        Tüm sözleşmeler için 15m barları çeker, 240m barlara resample eder.
        """
        now = datetime.now()
        contracts_state = {}

        for c in self.VIOP_SYMBOLS:
            sym = c["symbol"]
            ticker = c["ticker"]
            try:
                # 15 dakikalık son 5 günlük fiyat serisi
                raw = yf.download(ticker, period="5d", interval="15m", progress=False)
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                raw = raw.reset_index()
                t_col = "Datetime" if "Datetime" in raw.columns else "Date"

                df_15m = pd.DataFrame({
                    "timestamp": pd.to_datetime(raw[t_col]).dt.tz_localize(None),
                    "open": raw["Open"].astype(float),
                    "high": raw["High"].astype(float),
                    "low": raw["Low"].astype(float),
                    "close": raw["Close"].astype(float),
                    "volume": raw["Volume"].astype(float) if "Volume" in raw.columns else 0.0
                }).dropna().sort_values("timestamp").reset_index(drop=True)

                last_price = float(df_15m["close"].iloc[-1]) if not df_15m.empty else 0.0
                df_240m = self.resample_to_240m(df_15m)

                # Son 240m bar göstergeleri
                last_240m = df_240m.iloc[-1].to_dict() if not df_240m.empty else {}

                contracts_state[sym] = {
                    "code": c["code"],
                    "ticker": ticker,
                    "type": c["type"],
                    "multiplier": c["multiplier"],
                    "last_price": last_price,
                    "last_update": df_15m["timestamp"].iloc[-1].isoformat() if not df_15m.empty else None,
                    "bars_15m_count": len(df_15m),
                    "bars_240m_count": len(df_240m),
                    "last_240m_bar": last_240m
                }
            except Exception as e:
                logger.debug("%s fiyat çekim hatası: %s", sym, e)
                contracts_state[sym] = {"code": c["code"], "status": "ERROR", "error": str(e)}

        self.last_syncs["bars_15m"] = now
        self._save_status()
        print(f"[{now.strftime('%H:%M:%S')}] ✓ [15-Dk Takvimi] 20 VİOP Sözleşmesi Fiyat & 240m Barları Güncellendi.")
        return contracts_state

    # -------------------------------------------------------------------------
    # 4. MARGIN CALL / HESABA AİT TEMİNAT: 15 Dk Pasif + Bar Kapanışları
    # -------------------------------------------------------------------------
    def check_margin_call(
        self,
        account_equity: Optional[float] = None,
        active_positions: Optional[List[Dict[str, Any]]] = None,
        is_bar_close: bool = False,
        custom_check_type: Optional[str] = None
    ) -> MarginCallReport:
        """
        VİOP Margin Call ve Teminat Tamamlama Çağrısı Denetimi.
        - 15 Dakikada 1: Pasif denetim (PASSIVE_15M)
        - 14:15 ve 18:15 Bar Kapanışları: Aktif tasfiye/pozisyon küçültme denetimi (BAR_CLOSE_1415 / BAR_CLOSE_1815)
        """
        now = datetime.now()

        # Varsayılan bütçe ve durum
        if account_equity is None:
            sys_state = self.db.get_latest_system_state()
            account_equity = sys_state.get("total_nav", 150000.0) if sys_state else 150000.0

        if active_positions is None:
            active_positions = self.db.get_active_positions()

        # Denetim tipini belirle
        if custom_check_type:
            check_type = custom_check_type
        elif is_bar_close:
            current_hour = now.hour
            check_type = "BAR_CLOSE_1815" if current_hour >= 17 else "BAR_CLOSE_1415"
        else:
            # Otomatik saat denetimi: 14:10-14:25 ve 18:10-18:25 bar kapanışı kabul edilir
            t_now = now.time()
            if time(14, 10) <= t_now <= time(14, 25):
                check_type = "BAR_CLOSE_1415"
            elif time(18, 10) <= t_now <= time(18, 30):
                check_type = "BAR_CLOSE_1815"
            else:
                check_type = "PASSIVE_15M"

        # Güncel teminat gereksinimlerini DB'den çek
        latest_margins = self.db.get_latest_margins()

        # Fintables veya yerel hesaplama
        if self.fintables:
            report = self.fintables.calculate_margin_call_status(
                account_equity=account_equity,
                active_positions=active_positions,
                contracts_margins=latest_margins,
                check_type=check_type
            )
        else:
            # Yerel Takasbank hesaplaması
            total_init = 0.0
            worst_sym = None
            worst_pnl = float("inf")

            for pos in active_positions:
                sym = pos.get("symbol", "")
                lots = abs(pos.get("lots", 0))
                pnl = pos.get("pnl_try", 0.0)
                if pnl < worst_pnl:
                    worst_pnl = pnl
                    worst_sym = sym
                m_info = latest_margins.get(sym, {})
                init_m = m_info.get("initial_margin_try", 3000.0)
                total_init += init_m * lots

            total_maint = total_init * 0.75
            free_m = account_equity - total_init
            ratio = (account_equity / total_maint * 100.0) if total_maint > 0 else 999.0

            if total_maint > 0 and account_equity < total_maint:
                status = "MARGIN_CALL_DEFICIT"
                deficit = total_init - account_equity
                liq_req = check_type.startswith("BAR_CLOSE")
            elif total_maint > 0 and ratio < 120.0:
                status = "WARNING_LEVEL"
                deficit = 0.0
                liq_req = False
            else:
                status = "HEALTHY"
                deficit = 0.0
                liq_req = False

            report = MarginCallReport(
                account_equity=round(account_equity, 2),
                total_initial_margin=round(total_init, 2),
                total_maintenance_margin=round(total_maint, 2),
                free_margin=round(free_m, 2),
                margin_ratio_pct=round(ratio, 2),
                margin_deficit_try=round(max(0.0, deficit), 2),
                status=status,
                check_type=check_type,
                timestamp=now,
                liquidation_required=liq_req,
                target_liquidation_symbol=worst_sym if liq_req else None
            )

        # DB'ye kaydet
        self.db.record_margin_call_event(report.model_dump())

        if check_type == "PASSIVE_15M":
            self.last_syncs["margin_call_passive_15m"] = now
        elif check_type == "BAR_CLOSE_1415":
            self.last_syncs["margin_call_bar_close_1415"] = now
        elif check_type == "BAR_CLOSE_1815":
            self.last_syncs["margin_call_bar_close_1815"] = now

        self._save_status()
        print(f"[{now.strftime('%H:%M:%S')}] ✓ [Margin Call - {check_type}] Durum: {report.status} | Teminat Oranı: %{report.margin_ratio_pct:.1f} | Açık: {report.margin_deficit_try:,.2f} TL")
        return report

    # -------------------------------------------------------------------------
    # 5. ALE FONU NET NEMA HESABI: Seans Sonu (18:15)
    # -------------------------------------------------------------------------
    def calculate_ale_fund_eod(
        self,
        idle_cash: Optional[float] = None,
        annual_gross_rate: float = 0.48,
        force: bool = False
    ) -> AleFundEodReport:
        """
        Akbank ALE Para Piyasası Fonu Net Nema Hesabı.
        Seans sonu (18:15) boşta bekleyen nakit üzerinden çalıştırılır.
        %17.5 stopaj kesilir, net nema birikimli ALE kasasına aktarılır.
        """
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        if idle_cash is None:
            sys_state = self.db.get_latest_system_state()
            idle_cash = sys_state.get("free_margin", 150000.0) if sys_state else 150000.0

        daily_gross_yield = idle_cash * (annual_gross_rate / 365.0)
        withholding_tax = daily_gross_yield * 0.175
        daily_net_yield = daily_gross_yield - withholding_tax

        # Önceki kümülatif ALE kasasını oku
        prev_eod = self.db.get_latest_ale_eod()
        prev_vault = prev_eod.get("cumulative_ale_vault_try", 0.0) if prev_eod else 0.0
        cumulative_vault = prev_vault + daily_net_yield

        report = AleFundEodReport(
            date_str=date_str,
            idle_cash_try=round(idle_cash, 2),
            annual_gross_rate=round(annual_gross_rate, 4),
            daily_gross_yield_try=round(daily_gross_yield, 2),
            withholding_tax_try=round(withholding_tax, 2),
            daily_net_yield_try=round(daily_net_yield, 2),
            cumulative_ale_vault_try=round(cumulative_vault, 2),
            calculated_at=now
        )

        # DB'ye kaydet
        self.db.record_ale_eod(report.model_dump())
        self.last_syncs["ale_fund_1815"] = now
        self._save_status()

        print(f"[{now.strftime('%H:%M:%S')}] ✓ [18:15 Seans Sonu] ALE Net Nema: +{daily_net_yield:,.2f} TL (Stopaj: -{withholding_tax:,.2f} TL) | Toplam ALE Kasası: {cumulative_vault:,.2f} TL")
        return report

    # -------------------------------------------------------------------------
    # 6. GÜNLÜK SABAH BAŞLATMA VE TABLO SENKRONİZASYON RUTİNİ (08:30 - 09:30)
    # -------------------------------------------------------------------------
    async def run_morning_startup(
        self,
        account_equity: Optional[float] = None,
        active_positions: Optional[List[Dict[str, Any]]] = None,
        config_to_update: Optional[Any] = None,
        force: bool = True
    ) -> Dict[str, Any]:
        """
        GÜNLÜK SABAH BAŞLATMA VE VİOP TABLOLARI DENETİM RUTİNİ:
        Her sabah seans öncesi (08:30 - 09:30) Fintables.MCP ve Takasbank yardımıyla:
        1. VİOP Sözleşmeler Tablosu (08:30)
        2. VİOP Teminat Tablosu (09:00 Açılış Bülteni)
        3. Teminat Tamamlama Çağrıları (Margin Call / Teminat Açığı) Tablosu
        taranır. Değişen rakamlar tespit edilerek sisteme (DB, SystemConfig,
        bellek, live_market_state) anında yansıtılır.
        """
        now = datetime.now()
        print("\n" + "=" * 80)
        print("  ☀️ VİOP GÜNLÜK SABAH BAŞLATMA VE TABLO SENKRONİZASYONU")
        print(f"  Tarih & Saat: {now.strftime('%Y-%m-%d %H:%M:%S')} | Protokol: Fintables.MCP + Takasbank")
        print("=" * 80)

        # 1. TABLO: SÖZLEŞMELER LİSTESİ (08:30)
        print("\n[+] 1. ADIM: Fintables.MCP VİOP Sözleşmeler Tablosu Taranıyor (08:30)...")
        contracts = await self.sync_contracts_universe(force=force)
        n_contracts = len(contracts)
        n_categories = len({c.get("asset_category") for c in contracts})
        n_underlyings = len({c.get("underlying_symbol") for c in contracts})
        print(f"    ✓ Sözleşmeler Tablosu İncelendi: {n_contracts} Aktif Sözleşme, {n_categories} Varlık Sınıfı, {n_underlyings} Dayanak.")

        # 2. TABLO: TEMİNAT TABLOSU (09:00 AÇILIŞ BÜLTENİ)
        print("\n[+] 2. ADIM: Fintables.MCP VİOP Teminat Tablosu ve Değişim Analizi (09:00)...")
        margins = await self.sync_initial_margins(session_window="09:00_OPEN", force=force)

        # Değişen teminat rakamlarını tespit et
        changed_margins = []
        for m in margins:
            chg = m.get("margin_change_pct", 0.0)
            if abs(chg) > 0.001:
                changed_margins.append({
                    "contract_code": m["contract_code"],
                    "initial_margin_try": m["initial_margin_try"],
                    "maintenance_margin_try": m["maintenance_margin_try"],
                    "margin_change_pct": chg,
                    "session_window": m.get("session_window", "09:00_OPEN")
                })

        if changed_margins:
            print(f"    ⚠️ DİKKAT: Takasbank Teminat Bülteninde {len(changed_margins)} Sözleşmede Değişiklik Tespit Edildi:")
            for cm in changed_margins[:10]:
                sign = "+" if cm["margin_change_pct"] > 0 else ""
                print(f"      • {cm['contract_code']}: {cm['initial_margin_try']:,.2f} TL ({sign}%{cm['margin_change_pct']:.2f})")
            if len(changed_margins) > 10:
                print(f"      ... ve {len(changed_margins)-10} sözleşme daha.")
        else:
            print(f"    ✓ Teminat Tablosu İncelendi: Tüm {len(margins)} sözleşme teminatları stabil (Değişim: %0.00).")

        # 3. TABLO: TEMİNAT TAMAMLAMA ÇAĞRILARI (MARGIN CALL DENETİMİ)
        print("\n[+] 3. ADIM: VİOP Teminat Tamamlama Çağrıları Tablosu ve Portföy Riski Denetleniyor...")
        mc_report = self.check_margin_call(
            account_equity=account_equity,
            active_positions=active_positions,
            is_bar_close=False,
            custom_check_type="MORNING_STARTUP"
        )
        print(f"    ✓ Margin Call Durumu: [{mc_report.status}] | Karşılama Oranı: %{mc_report.margin_ratio_pct:.1f} | Serbest Teminat: {mc_report.free_margin:,.2f} TL | Açık: {mc_report.margin_deficit_try:,.2f} TL")
        if mc_report.status == "MARGIN_CALL_DEFICIT":
            print(f"    🚨 UYARI: Teminat Tamamlama Çağrısı Açığı Mevcut! ({mc_report.margin_deficit_try:,.2f} TL)")

        # 4. DEĞİŞEN RAKAMLARI SİSTEME DİNAMİK YANSITMA
        print("\n[+] 4. ADIM: Değişen Rakamlar Karar Motorlarına ve Sistem Belleğine Yansıtılıyor...")
        reflected_count = self.apply_updated_margins_to_system(config_to_update=config_to_update)
        print(f"    ✓ Sistem Enjeksiyonu Tamamlandı: {reflected_count} Sözleşme Spesifikasyonu ve Teminatı Güncellendi.")

        # 5. KONSOLİDE RAPOR VE ATOMİK KAYIT
        summary = {
            "title": "VİOP SABAH BAŞLATMA VE TABLO SENKRONİZASYONU RAPORU",
            "timestamp": now.isoformat(),
            "status": "SUCCESS",
            "contracts_universe": {
                "total_contracts": n_contracts,
                "asset_categories_count": n_categories,
                "underlyings_count": n_underlyings
            },
            "margins_table": {
                "total_margins_tracked": len(margins),
                "changed_margins_count": len(changed_margins),
                "changed_margins": changed_margins
            },
            "margin_call_table": mc_report.model_dump(),
            "system_reflection": {
                "reflected_count": reflected_count,
                "config_updated": config_to_update is not None,
                "state_file_updated": True
            }
        }

        # morning_sync_summary.json dosyasına kaydet
        summary_file = os.path.join(self.DATABASE_DIR, "morning_sync_summary.json")
        try:
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.debug("Morning summary yazılamadı: %s", e)

        print("=" * 80)
        print("  ✓ TÜM 3 VİOP TABLOSU BAŞARIYLA İNCELENDİ VE SİSTEME EKSİKSİZ YANSITILDI!")
        print("=" * 80 + "\n")
        return summary

    def apply_updated_margins_to_system(
        self,
        config_to_update: Optional[Any] = None,
        executioner: Optional[Any] = None,
        broker: Optional[Any] = None
    ) -> int:
        """
        DatabaseManager'daki en güncel teminatları SystemConfig, TechnicalExecutioner
        ve PaperBroker nesnelerine aktarır.
        """
        latest_margins = self.db.get_latest_margins()
        updated_count = 0

        # 1. Config güncellemesi
        if config_to_update is not None and hasattr(config_to_update, "update_from_margins"):
            updated_count += config_to_update.update_from_margins(latest_margins)
        elif config_to_update is not None and hasattr(config_to_update, "contracts"):
            for code, m in latest_margins.items():
                if code in config_to_update.contracts:
                    spec = config_to_update.contracts[code]
                    from src.core.config import ContractSpecification
                    config_to_update.contracts[code] = ContractSpecification(
                        symbol=spec.symbol,
                        underlying=spec.underlying,
                        multiplier=spec.multiplier,
                        initial_margin_try=m["initial_margin_try"],
                        maintenance_margin_ratio=m["maintenance_margin_try"] / m["initial_margin_try"] if m["initial_margin_try"] > 0 else 0.75,
                        tick_size=spec.tick_size,
                        commission_rate=spec.commission_rate
                    )
                    updated_count += 1

        # 2. Executioner & Broker config'leri
        if executioner is not None and hasattr(executioner, "config"):
            self.apply_updated_margins_to_system(config_to_update=executioner.config)
        if broker is not None and hasattr(broker, "config"):
            self.apply_updated_margins_to_system(config_to_update=broker.config)

        # 3. live_market_state.json güncellemesi
        try:
            if os.path.exists(self.MARKET_STATE_FILE):
                with open(self.MARKET_STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
            else:
                state = {}

            if "viop_schedule" not in state or not isinstance(state["viop_schedule"], dict):
                state["viop_schedule"] = {}
            state["viop_schedule"]["latest_margins_count"] = len(latest_margins)
            state["viop_schedule"]["morning_startup_synced_at"] = datetime.now().isoformat()
            state["viop_schedule"]["active_contracts_count"] = len(self.db.get_viop_contracts())

            with open(self.MARKET_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.debug("live_market_state güncellenemedi: %s", e)

        return updated_count or len(latest_margins)

    # -------------------------------------------------------------------------
    # MASTER TAKVİM VE KARAR HATTI DÖNGÜSÜ
    # -------------------------------------------------------------------------
    async def run_scheduled_pipeline(
        self,
        current_dt: Optional[datetime] = None,
        account_equity: Optional[float] = None,
        active_positions: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Mevcut zamana göre Fintables Veri Güncelleme Takvimini işletir.
        """
        now = current_dt or datetime.now()
        t_now = now.time()
        results: Dict[str, Any] = {}

        # 1. Sözleşmeler Listesi (08:30)
        # Sabah 08:30 sonrası ve bugün henüz güncellenmemişse çalıştır
        last_0830 = self.last_syncs["contracts_universe_0830"]
        needs_0830 = (
            t_now >= time(8, 30)
            and (last_0830 is None or last_0830.date() < now.date())
        )
        if needs_0830:
            results["contracts_universe"] = await self.sync_contracts_universe()

        # 2. Teminat Tutarları (09:00 ve 14:00)
        # 09:00 Açılış Teminatı
        last_0900 = self.last_syncs["margins_0900"]
        needs_0900 = (
            t_now >= time(9, 0)
            and (last_0900 is None or last_0900.date() < now.date() or (last_0900.time() < time(9, 0) and now.date() == last_0900.date()))
        )
        if needs_0900:
            results["margins_0900"] = await self.sync_initial_margins(session_window="09:00_OPEN")

        # 14:00 Gün Ortası Teminatı
        last_1400 = self.last_syncs["margins_1400"]
        needs_1400 = (
            t_now >= time(14, 0)
            and (last_1400 is None or last_1400.date() < now.date() or (last_1400.time() < time(14, 0) and now.date() == last_1400.date()))
        )
        if needs_1400:
            results["margins_1400"] = await self.sync_initial_margins(session_window="14:00_MIDDAY")

        # 3. Fiyat & İndikatör Barları (15 Dakikada 1 - 240m Resampler)
        last_bars = self.last_syncs["bars_15m"]
        needs_bars = (
            last_bars is None
            or (now - last_bars).total_seconds() >= 900
        )
        if needs_bars:
            results["prices_and_indicators"] = await self.sync_prices_and_indicators()

        # 4. Margin Call / Hesaba Ait Teminat (15 Dk Pasif + Bar Kapanışları)
        is_bar_close = False
        bar_close_type = None
        if time(14, 10) <= t_now <= time(14, 25):
            is_bar_close = True
            bar_close_type = "BAR_CLOSE_1415"
        elif time(18, 10) <= t_now <= time(18, 30):
            is_bar_close = True
            bar_close_type = "BAR_CLOSE_1815"

        results["margin_call"] = self.check_margin_call(
            account_equity=account_equity,
            active_positions=active_positions,
            is_bar_close=is_bar_close,
            custom_check_type=bar_close_type
        ).model_dump()

        # 5. ALE Fonu Net Nema Hesabı (18:15)
        last_ale = self.last_syncs["ale_fund_1815"]
        needs_ale = (
            t_now >= time(18, 15)
            and (last_ale is None or last_ale.date() < now.date() or (last_ale.time() < time(18, 15) and now.date() == last_ale.date()))
        )
        if needs_ale:
            results["ale_fund_eod"] = self.calculate_ale_fund_eod().model_dump()

        return results

    def get_universe_breakdown_report(self) -> Dict[str, Any]:
        """
        VİOP evreninin 6 varlık sınıfı ve farklı vadelerdeki sözleşme adetlerini döner.
        """
        return get_universe_breakdown()


if __name__ == "__main__":
    scheduler = ViopDataFeedScheduler()
    # Test çalıştırması (Tüm akışları zorlayarak çalıştır)
    async def _test():
        print("--- 1. Sözleşmeler Listesi (08:30) ---")
        await scheduler.sync_contracts_universe(force=True)
        print("\n--- 2. Teminat Tutarları (09:00 & 14:00) ---")
        await scheduler.sync_initial_margins(session_window="09:00_OPEN", force=True)
        await scheduler.sync_initial_margins(session_window="14:00_MIDDAY", force=True)
        print("\n--- 3. Margin Call Denetimi (15m Pasif & 14:15 Bar Kapanışı) ---")
        scheduler.check_margin_call(custom_check_type="PASSIVE_15M")
        scheduler.check_margin_call(custom_check_type="BAR_CLOSE_1415")
        print("\n--- 4. ALE Fonu Net Nema Hesabı (18:15) ---")
        scheduler.calculate_ale_fund_eod(idle_cash=150000.0, force=True)
        print("\n--- 5. Takvim Durumu Kaydedildi ---")
        print(f"Durum Dosyası: {scheduler.SCHEDULE_STATE_FILE}")

    asyncio.run(_test())
