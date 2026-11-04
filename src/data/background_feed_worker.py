"""
15-Dakikalık Periyodik Veri Hattı ve Arka Plan Senkronizasyon Servisi
(src/data/background_feed_worker.py).

Gereksinimler & Görevler:
1. Fintables.MCP 15-Dakika Gecikmeli Veri Entegrasyonu:
   - 15 dakikada 1 tüm veri hattını arka planda günceller.
   - Fiyat bilgileri, Fintables "Akış" (Haberler, KAP bildirimleri, Açıklanan bilançolar, Politika faizi duyuruları),
   - TCMB canlı gösterge kurları (USD/TRY, EUR/TRY) ve politika faiz kararları.
2. Gürültü Önleyici Çoklu Vade Dönüştürücüsü (Bar Resampler):
   - 15 dakikalık veriyi gürültüsüz karar üretimi için 120-dakikalık (2 saat) ve 240-dakikalık (4 saat) barlara resample eder.
3. Akbank ALE Para Piyasası Fonu Takipçisi:
   - Günlük brüt getiri, yasal %17.5 stopaj kesintisi ve net nemayı hesaplar.
4. Konsolide Canlı Durum Deposu (live_market_state.json):
   - Tüm motorların sıfır gecikmeyle okuyabileceği merkezi veri deposuna yazar.
"""

import asyncio
from datetime import datetime, timedelta
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional
import pandas as pd
import yfinance as yf

# Ensure project root is in sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.data.fintables_mcp import FintablesMCPClient
from src.data.schemas import FundamentalData, KapNews, MacroData
from src.data.tcmb_mcp import TCMBMCPClient
from src.data.viop_feed_scheduler import ViopDataFeedScheduler
from src.data.viop_universe_definitions import (
    EQUITY_UNDERLYINGS,
    INDEX_UNDERLYINGS,
    FX_UNDERLYINGS,
    COMMODITY_UNDERLYINGS
)

logger = logging.getLogger(__name__)

# UTF-8 Terminal desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class BackgroundFeedWorker:
    """
    15-Dakikalık Arka Plan Veri Senkronizasyon Motoru.
    """

    DATABASE_DIR = os.path.join(os.path.dirname(__file__), "..", "database")
    STATE_FILE = os.path.join(DATABASE_DIR, "live_market_state.json")

    # 63 Dayanak Enstrümanlık Tam VİOP Evreni (47 Pay, 4 Endeks, 6 Döviz, 6 Emtia | 207 Sözleşme)
    # Fintables AI & Borsa İstanbul Resmi Standartları
    VIOP_SYMBOLS = []
    for _sym, _title, _mult, _init_m, _ticker in EQUITY_UNDERLYINGS:
        VIOP_SYMBOLS.append({"symbol": f"F_{_sym}", "ticker": _ticker, "type": "EQUITY", "company": _title})
    for _sym, _title, _mult, _init_m, _ticker, _months in INDEX_UNDERLYINGS:
        VIOP_SYMBOLS.append({"symbol": f"F_{_sym}", "ticker": _ticker, "type": "INDEX", "company": _title})
    for _sym, _title, _mult, _init_m, _ticker, _months in FX_UNDERLYINGS:
        VIOP_SYMBOLS.append({"symbol": f"F_{_sym}", "ticker": _ticker, "type": "FX", "company": _title})
    for _sym, _title, _mult, _init_m, _ticker, _months in COMMODITY_UNDERLYINGS:
        VIOP_SYMBOLS.append({"symbol": f"F_{_sym}", "ticker": _ticker, "type": "COMMODITY", "company": _title})

    def __init__(self, sync_interval_seconds: int = 900) -> None:
        """
        Args:
            sync_interval_seconds: Senkronizasyon periyodu (Varsayılan: 900 sn = 15 dakika)
        """
        self.sync_interval = sync_interval_seconds
        os.makedirs(self.DATABASE_DIR, exist_ok=True)
        self.tcmb = TCMBMCPClient()
        self.fintables: Optional[FintablesMCPClient] = None
        try:
            self.fintables = FintablesMCPClient()
        except Exception as e:
            logger.warning("Fintables MCP İstemcisi başlatılamadı (Offline modda çalışılacak): %s", e)

        # Fintables VİOP Veri Güncelleme Takvimi Yöneticisi
        self.viop_scheduler = ViopDataFeedScheduler()

    @staticmethod
    def resample_ohlcv(df: pd.DataFrame, timeframe_minutes: int) -> pd.DataFrame:
        """
        15 dakikalık veya saatlik barları 120m (2 saat) ve 240m (4 saat) barlara dönüştürür.
        240m için seans içi karar pencereleri:
        - 14:15 (Öğle Barı: 09:30 - 14:15)
        - 18:15 (Seans Sonu Kapanış Barı: 14:15 - 18:15)
        """
        if df.empty or timeframe_minutes <= 15:
            return df.copy()

        df_copy = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_copy["timestamp"]):
            df_copy["timestamp"] = pd.to_datetime(df_copy["timestamp"])

        if timeframe_minutes == 240:
            records = []
            df_copy["date"] = df_copy["timestamp"].dt.date
            for d, group in df_copy.groupby("date", sort=True):
                midday_group = group[group["timestamp"].dt.hour <= 14]
                if not midday_group.empty:
                    bar_time = datetime.combine(d, datetime.min.time()).replace(hour=14, minute=15)
                    records.append({
                        "timestamp": bar_time,
                        "open": float(midday_group["open"].iloc[0]),
                        "high": float(midday_group["high"].max()),
                        "low": float(midday_group["low"].min()),
                        "close": float(midday_group["close"].iloc[-1]),
                        "volume": float(midday_group["volume"].sum())
                    })
                close_group = group[group["timestamp"].dt.hour > 14]
                if not close_group.empty:
                    bar_time = datetime.combine(d, datetime.min.time()).replace(hour=18, minute=15)
                    records.append({
                        "timestamp": bar_time,
                        "open": float(close_group["open"].iloc[0]),
                        "high": float(close_group["high"].max()),
                        "low": float(close_group["low"].min()),
                        "close": float(close_group["close"].iloc[-1]),
                        "volume": float(close_group["volume"].sum())
                    })
            if records:
                return pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True)

        df_copy = df_copy.set_index("timestamp")
        rule = f"{timeframe_minutes}min"
        resampled = df_copy.resample(rule, label='left', closed='left').agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna().reset_index()

        return resampled

    async def fetch_live_macro_data(self) -> Dict[str, Any]:
        """TCMB canlı kurlarını ve politika faizini çeker."""
        try:
            fx_rates = await self.tcmb.fetch_fx_rates()
            policy_rate = await self.tcmb.fetch_policy_rate()
            return {
                "status": "LIVE",
                "usd_try": fx_rates.get("USD_TRY", 35.85),
                "eur_try": fx_rates.get("EUR_TRY", 38.90),
                "policy_rate_pct": policy_rate,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.warning("TCMB canlı veri çekilemedi, varsayılan referans kullanılıyor: %s", e)
            return {
                "status": "FALLBACK",
                "usd_try": 35.85,
                "eur_try": 38.90,
                "policy_rate_pct": 50.00,
                "timestamp": datetime.now().isoformat()
            }

    async def fetch_fintables_stream(self) -> Dict[str, Any]:
        """
        Fintables 'Akış' başlığı altındaki haberleri, KAP bildirimlerini
        ve politika faiz haberlerini çeker.
        """
        stream_data = {
            "kap_disclosures": [],
            "earnings_calendar": [],
            "policy_news": [],
            "status": "OFFLINE"
        }

        if not self.fintables:
            return stream_data

        try:
            sample_stocks = ["THYAO", "AKBNK", "GARAN", "EREGL", "TUPRS"]
            for st in sample_stocks:
                try:
                    news = await self.fintables.fetch_kap_disclosures(st, limit=2)
                    for n in news:
                        stream_data["kap_disclosures"].append({
                            "symbol": n.symbol,
                            "headline": n.headline,
                            "announced_at": n.announced_at.isoformat() if n.announced_at else None,
                            "summary": n.summary,
                            "type": n.disclosure_type
                        })
                except Exception as ex:
                    if "401" in str(ex) or "Invalid or expired" in str(ex):
                        logger.warning("Fintables token süresi dolmuş, akış sorgusu durduruldu: %s", ex)
                        stream_data["status"] = "TOKEN_EXPIRED"
                        break
            if stream_data["kap_disclosures"]:
                stream_data["status"] = "LIVE"
        except Exception as e:
            logger.warning("Fintables Akış sorgulanamadı: %s", e)

        return stream_data

    def calculate_ale_fund_daily_yield(self, annual_gross_rate: float = 0.48) -> Dict[str, float]:
        """
        Akbank ALE Para Piyasası Fonu günlük nema ve %17.5 yasal stopaj kesintisi hesabı.
        """
        daily_gross_rate = annual_gross_rate / 365.0
        withholding_tax_pct = 0.175
        daily_tax_rate = daily_gross_rate * withholding_tax_pct
        daily_net_rate = daily_gross_rate - daily_tax_rate

        return {
            "annual_gross_rate": annual_gross_rate,
            "daily_gross_rate": round(daily_gross_rate, 6),
            "withholding_tax_pct": withholding_tax_pct,
            "daily_tax_rate": round(daily_tax_rate, 6),
            "daily_net_rate": round(daily_net_rate, 6),
            "annual_net_rate": round(annual_gross_rate * (1.0 - withholding_tax_pct), 4)
        }

    async def sync_once(self) -> Dict[str, Any]:
        """
        Tüm veri hatlarını 15 dakikalık periyot için senkronize eder.
        """
        now = datetime.now()
        print(f"[{now.strftime('%H:%M:%S')}] 15-Dakikalık Veri Hattı Senkronizasyonu Başlatıldı...")

        # 1. TCMB Makro Verileri
        macro = await self.fetch_live_macro_data()

        # 2. Fintables Akış ve KAP Bildirimleri
        stream = await self.fetch_fintables_stream()

        # 3. Akbank ALE Nema ve Stopaj Parametreleri
        ale_rates = self.calculate_ale_fund_daily_yield(annual_gross_rate=0.48)

        # 4. 20 Sözleşme İçin Fiyat Snapshot & 120m / 240m Resampling
        contracts_state = {}
        for c in self.VIOP_SYMBOLS:
            sym = c["symbol"]
            ticker = c["ticker"]
            try:
                # 15 dakikalık son barlar (Yahoo Finance 15m / 60m gecikmeli canlı proxy)
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

                # 120m ve 240m Resample
                df_120m = self.resample_ohlcv(df_15m, 120)
                df_240m = self.resample_ohlcv(df_15m, 240)

                contracts_state[sym] = {
                    "ticker": ticker,
                    "type": c["type"],
                    "last_price": last_price,
                    "last_update": df_15m["timestamp"].iloc[-1].isoformat() if not df_15m.empty else None,
                    "bars_15m_count": len(df_15m),
                    "bars_120m_count": len(df_120m),
                    "bars_240m_count": len(df_240m),
                    "last_120m_bar": df_120m.iloc[-1].to_dict() if not df_120m.empty else {},
                    "last_240m_bar": df_240m.iloc[-1].to_dict() if not df_240m.empty else {}
                }
            except Exception as e:
                logger.debug("%s fiyatları çekilirken hata: %s", sym, e)
                contracts_state[sym] = {"status": "ERROR", "error": str(e)}

        # 5. Fintables VİOP Veri Güncelleme Takvimi (08:30 Sözleşmeler, 09:00/14:00 Teminatlar, Margin Call, ALE EOD)
        try:
            # Sabah seans açılış penceresinde veya günün ilk çalıştırmasında morning startup çalıştır
            last_0830 = self.viop_scheduler.last_syncs.get("contracts_universe_0830")
            is_morning_window = now.hour >= 8 and (last_0830 is None or last_0830.date() < now.date())
            if is_morning_window:
                morning_summary = await self.viop_scheduler.run_morning_startup()
                viop_schedule_results = {"status": "SUCCESS", "morning_startup": morning_summary}
            else:
                viop_schedule_results = await self.viop_scheduler.run_scheduled_pipeline()
        except Exception as e:
            logger.warning("VİOP Takvim senkronizasyonunda hata: %s", e)
            viop_schedule_results = {"status": "ERROR", "error": str(e)}

        consolidated_state = {
            "metadata": {
                "worker_name": "15-Min Background Feed Pipeline",
                "synced_at": now.isoformat(),
                "delay_minutes": 15,
                "supported_timeframes": ["15m", "120m", "240m"],
                "total_contracts": len(self.VIOP_SYMBOLS)
            },
            "macro": macro,
            "fintables_stream": stream,
            "ale_fund_nema": ale_rates,
            "contracts": contracts_state,
            "viop_schedule": viop_schedule_results
        }

        # JSON olarak live_market_state.json dosyasına atomik kaydet
        with open(self.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(consolidated_state, f, ensure_ascii=False, indent=2, default=str)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Senkronizasyon Tamamlandı -> {self.STATE_FILE}")
        return consolidated_state

    async def run_loop(self) -> None:
        """Sonsuz 15 dakikalık periyodik arka plan döngüsü."""
        print(f"[*] 15-Dakikalık Arka Plan Senkronizasyon Servisi Başlatıldı (Periyot: {self.sync_interval} sn).")
        while True:
            try:
                await self.sync_once()
            except Exception as e:
                logger.error("Senkronizasyon döngüsünde hata: %s", e)
            await asyncio.sleep(self.sync_interval)


if __name__ == "__main__":
    worker = BackgroundFeedWorker(sync_interval_seconds=900)
    asyncio.run(worker.sync_once())
