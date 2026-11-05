"""
🏛️ VİOP TAM OTOMATİK CANLI OPERASYON VE KARAR MOTORU (v4.2)
(src/execution/autonomous_operator.py)

BU MODÜL KULLANICI MÜDAHALESİ GEREKTİRMEYEN (ZERO MANUAL INTERVENTION) OTONOM PİLOT ÇEKİRDEĞİDİR.

Görevleri:
1. Otonom Sabah Başlatma: Her sabah 08:30 - 09:30 penceresinde (veya bot gün içinde ilk açıldığında)
   Fintables.MCP ve Takasbank üzerinden 3 VİOP tablosunu inceler:
   - 1. Sözleşmeler Listesi (08:30)
   - 2. Teminat Tablosu (09:00 Açılış Bülteni & Değişim Analizi)
   - 3. Teminat Tamamlama Çağrıları (Margin Call / Teminat Açığı)
   Değişen tüm rakamları anında karar ve risk motorlarına yansıtır.
2. 15-Dakikalık Fiyat & 240m Karar Pencereleri (14:15 ve 18:15):
   - Ali Perşembe Doktrini (Temel Pusula + Teknik İcra Motoru) ile sinyalleri değerlendirir.
   - Giriş, +2R bedava piramitleme (Scale-Out 33), Chandelier Stop ve kâr al işlemlerini icra eder.
3. Otomatik Sanal Emir İletimi (PaperBroker):
   - Midas çift taraflı kademeli komisyonu ve güncel Takasbank teminatıyla işlemleri gerçekleştirir.
   - Tüm işlemleri ve açık pozisyonları SQLite veritabanına (`viop_trading.db`) yazar.
4. Seans Sonu Otomatik Nema (18:15):
   - Boşta kalan serbest teminata Akbank ALE Para Piyasası Fonu (%17.5 net) nemasını işletir.
"""

import asyncio
from datetime import datetime, time, timedelta
import json
import logging
import os
import socket
import sys
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import yfinance as yf

# Proje ana dizinini sys.path'e ekle
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.core.config import SystemConfig, ContractSpecification
from src.database.db_manager import DatabaseManager
from src.data.viop_feed_scheduler import ViopDataFeedScheduler
from src.data.fintables_mcp import FintablesMCPClient
from src.data.tcmb_mcp import TCMBMCPClient
from src.data.viop_universe_definitions import (
    EQUITY_UNDERLYINGS,
    INDEX_UNDERLYINGS,
    FX_UNDERLYINGS,
    COMMODITY_UNDERLYINGS
)
from src.execution.paper_broker import PaperBroker
from src.strategy.portfolio_manager import PortfolioRiskManager, TradingMode
from src.strategy.fundamental_compass import (
    AssetChannel,
    CostOfCarryInput,
    DirectionalBias,
    FundamentalCompass,
    MarketMicrostructureInput
)
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalDecisionV4,
    TechnicalExecutioner
)

# Log Yapılandırması (autonomous_operator.log)
log_file_path = os.path.join(project_root, "autonomous_operator.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("AutonomousOperator")


def acquire_operator_lock(port: int = 58999) -> Optional[socket.socket]:
    """
    Sistemin aynı anda sadece TEK bir otonom canlı operatör çalıştırmasını
    garanti eden soket tabanlı kilit mekanizması (Cross-process singleton).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", port))
        return s
    except OSError:
        return None


class AutonomousLiveOperator:
    """
    Sıfır Müdahaleli VİOP Otonom Canlı Operatörü.
    """

    DATABASE_DIR = os.path.join(project_root, "src", "database")
    STATE_FILE = os.path.join(DATABASE_DIR, "live_market_state.json")

    # 63 Dayanak Enstrümanlık Tam VİOP Evreni (47 Pay, 4 Endeks, 6 Döviz, 6 Emtia | 207 Sözleşme)
    # Fintables AI & Borsa İstanbul Resmi Standartları
    PORTFOLIO_SYMBOLS = []
    for _sym, _title, _mult, _init_m, _ticker in EQUITY_UNDERLYINGS:
        PORTFOLIO_SYMBOLS.append({
            "symbol": f"F_{_sym}", "ticker": _ticker, "category": "EQUITY", "company": _title
        })
    for _sym, _title, _mult, _init_m, _ticker, _months in INDEX_UNDERLYINGS:
        PORTFOLIO_SYMBOLS.append({
            "symbol": f"F_{_sym}", "ticker": _ticker, "category": "INDEX", "company": _title
        })
    for _sym, _title, _mult, _init_m, _ticker, _months in FX_UNDERLYINGS:
        PORTFOLIO_SYMBOLS.append({
            "symbol": f"F_{_sym}", "ticker": _ticker, "category": "FX", "company": _title
        })
    for _sym, _title, _mult, _init_m, _ticker, _months in COMMODITY_UNDERLYINGS:
        PORTFOLIO_SYMBOLS.append({
            "symbol": f"F_{_sym}", "ticker": _ticker, "category": "COMMODITY", "company": _title
        })

    def __init__(self, initial_capital: float = 2_000_000.0) -> None:
        self.db = DatabaseManager()
        self.config = SystemConfig()
        
        # En son sistem durumunu oku veya başlat
        latest_sys = self.db.get_latest_system_state()
        if latest_sys and "total_nav" in latest_sys:
            active_capital = float(latest_sys["total_nav"])
        else:
            active_capital = initial_capital
            self.db.record_system_state(
                total_nav=active_capital,
                free_margin=active_capital,
                daily_pnl=0.0,
                daily_return_pct=0.0,
                trading_mode="LIVE_TRADING",
                consecutive_losses=0,
                circuit_breaker_active=False
            )
            self.db.record_equity_point(nav=active_capital, sma20=active_capital, mode="LIVE_TRADING")

        self.broker = PaperBroker(initial_capital=active_capital, config=self.config)
        self.risk_manager = PortfolioRiskManager(initial_capital=active_capital)
        self.executioner = TechnicalExecutioner(config=self.config)
        self.compass = FundamentalCompass()
        self.scheduler = ViopDataFeedScheduler(db=self.db)
        self.tcmb = TCMBMCPClient()

        self.fintables = None
        try:
            self.fintables = FintablesMCPClient()
        except Exception as e:
            logger.info("Fintables MCP bağlantısı offline/fallback modda: %s", e)

        # Takvim takip durumları
        self.last_morning_sync_date: Optional[str] = None
        self.last_ale_eod_date: Optional[str] = None

        # Veritabanında daha önce yapılmış morning sync var mı kontrol et
        summary_file = os.path.join(self.DATABASE_DIR, "morning_sync_summary.json")
        if os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    ts = d.get("timestamp", "")
                    if ts:
                        self.last_morning_sync_date = ts[:10]
            except Exception:
                pass

    async def ensure_morning_startup(self, force: bool = False) -> Dict[str, Any]:
        """
        Her sabah seans öncesi (veya günün ilk döngüsünde) 3 VİOP tablosunu
        kullanıcı müdahalesi olmadan otomatik inceler ve sisteme yansıtır.
        """
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # Bugün henüz çalıştırılmadıysa veya force=True ise çalıştır
        if self.last_morning_sync_date != today_str or force:
            logger.info("☀️ [OTONOM BAŞLATMA] 3 VİOP Tablosu Otomatik İnceleniyor (Sözleşmeler, Teminatlar, Margin Call)...")
            summary = await self.scheduler.run_morning_startup(
                account_equity=self.broker.current_nav,
                active_positions=self.db.get_active_positions(),
                config_to_update=self.config,
                force=True
            )
            # Karar ve icra motoru teminatlarını güncelle
            self.scheduler.apply_updated_margins_to_system(
                config_to_update=self.config,
                executioner=self.executioner,
                broker=self.broker
            )
            self.last_morning_sync_date = today_str
            chg_count = summary.get("margins_table", {}).get("changed_margins_count", 0)
            mc_status = summary.get("margin_call_table", {}).get("status", "HEALTHY")
            logger.info("✓ [OTONOM BAŞLATMA TAMAMLANDI] Değişen Teminat: %d | Margin Call Durumu: %s", chg_count, mc_status)
            return summary
        else:
            return {"status": "ALREADY_SYNCED_TODAY", "date": today_str}

    @staticmethod
    def resample_ohlcv(df_15m: pd.DataFrame, timeframe_minutes: int) -> pd.DataFrame:
        """15 dakikalık veriyi verilen periyotta resample eder (120m / 240m)."""
        if df_15m.empty:
            return pd.DataFrame()
        df = df_15m.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        if timeframe_minutes == 240:
            records = []
            df["date"] = df["timestamp"].dt.date
            for d, group in df.groupby("date", sort=True):
                midday = group[group["timestamp"].dt.hour <= 14]
                if not midday.empty:
                    bar_time = datetime.combine(d, datetime.min.time()).replace(hour=14, minute=15)
                    records.append({
                        "timestamp": bar_time,
                        "open": float(midday["open"].iloc[0]),
                        "high": float(midday["high"].max()),
                        "low": float(midday["low"].min()),
                        "close": float(midday["close"].iloc[-1]),
                        "volume": float(midday["volume"].sum())
                    })
                close_grp = group[group["timestamp"].dt.hour > 14]
                if not close_grp.empty:
                    bar_time = datetime.combine(d, datetime.min.time()).replace(hour=18, minute=15)
                    records.append({
                        "timestamp": bar_time,
                        "open": float(close_grp["open"].iloc[0]),
                        "high": float(close_grp["high"].max()),
                        "low": float(close_grp["low"].min()),
                        "close": float(close_grp["close"].iloc[-1]),
                        "volume": float(close_grp["volume"].sum())
                    })
            return pd.DataFrame(records).sort_values("timestamp").reset_index(drop=True) if records else pd.DataFrame()

        df_idx = df.set_index("timestamp")
        rule = f"{timeframe_minutes}min"
        resampled = df_idx.resample(rule, label='left', closed='left').agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna().reset_index()
        return resampled

    @staticmethod
    def resample_ohlcv_240m(df_15m: pd.DataFrame) -> pd.DataFrame:
        """15 dakikalık veriyi kurumsal 240m seans pencerelerine (14:15 ve 18:15) resample eder."""
        return AutonomousLiveOperator.resample_ohlcv(df_15m, 240)

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
        """Fintables 'Akış' haberleri ve KAP bildirimlerini çeker."""
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
                        logger.warning("Fintables token süresi dolmuş: %s", ex)
                        stream_data["status"] = "TOKEN_EXPIRED"
                        break
            if stream_data["kap_disclosures"]:
                stream_data["status"] = "LIVE"
        except Exception as e:
            logger.warning("Fintables Akış sorgulanamadı: %s", e)

        return stream_data

    def calculate_ale_fund_daily_yield(self, annual_gross_rate: float = 0.48) -> Dict[str, float]:
        """Akbank ALE Para Piyasası Fonu günlük nema ve %17.5 stopaj kesintisi hesabı."""
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

    async def fetch_contract_data(self, ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Yahoo Finance ve BIST proxy üzerinden 15m barları çeker, 120m ve 240m barlara resample eder."""
        raw_15m = yf.download(ticker, period="5d", interval="15m", progress=False)
        if isinstance(raw_15m.columns, pd.MultiIndex):
            raw_15m.columns = raw_15m.columns.get_level_values(0)
        raw_15m = raw_15m.reset_index()
        t_col = "Datetime" if "Datetime" in raw_15m.columns else "Date"

        df_15m = pd.DataFrame({
            "timestamp": pd.to_datetime(raw_15m[t_col]).dt.tz_localize(None),
            "open": raw_15m["Open"].astype(float),
            "high": raw_15m["High"].astype(float),
            "low": raw_15m["Low"].astype(float),
            "close": raw_15m["Close"].astype(float),
            "volume": raw_15m["Volume"].astype(float) if "Volume" in raw_15m.columns else 0.0
        }).dropna().sort_values("timestamp").reset_index(drop=True)

        df_120m = self.resample_ohlcv(df_15m, 120)
        df_240m = self.resample_ohlcv(df_15m, 240)
        return df_15m, df_120m, df_240m

    async def execute_autonomous_cycle(self) -> Dict[str, Any]:
        """
        Tek bir tam otonom döngü icra eder:
        1. Sabah başlatma kontrolü
        2. Fiyat ve barların çekilmesi
        3. Karar motoru değerlendirmesi
        4. PaperBroker ile otomatik icra
        5. Seans sonu ALE neması kontrolü
        6. Kalıcı veritabanı senkronizasyonu
        """
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        logger.info(">>> [OTONOM DÖNGÜ BAŞLADI] %s <<<", now.strftime("%Y-%m-%d %H:%M:%S"))

        # 1. Otonom Sabah Başlatma Denetimi
        await self.ensure_morning_startup(force=False)

        # 2. Makro, Akış ve ALE Nema Parametrelerini Çek
        macro = await self.fetch_live_macro_data()
        stream = await self.fetch_fintables_stream()
        ale_rates = self.calculate_ale_fund_daily_yield(annual_gross_rate=0.48)

        # Devre kesici kontrolü
        cb_active, cb_reason = self.risk_manager.check_circuit_breaker()
        executed_trades = []

        # 3. Portföydeki 20 Sözleşmeyi Otonom Değerlendir
        contracts_snapshot = {}
        for item in self.PORTFOLIO_SYMBOLS:
            sym = item["symbol"]
            ticker = item["ticker"]
            cat = item["category"]

            try:
                df_15m, df_120m, df_240m = await self.fetch_contract_data(ticker)
                if df_15m.empty:
                    continue

                curr_p = float(df_15m["close"].iloc[-1])
                self.broker.market_prices[sym] = curr_p
                contracts_snapshot[sym] = {
                    "ticker": ticker,
                    "type": cat,
                    "last_price": curr_p,
                    "last_update": df_15m["timestamp"].iloc[-1].isoformat() if not df_15m.empty else None,
                    "bars_15m_count": len(df_15m),
                    "bars_120m_count": len(df_120m),
                    "bars_240m_count": len(df_240m),
                    "last_120m_bar": df_120m.iloc[-1].to_dict() if not df_120m.empty else {},
                    "last_240m_bar": df_240m.iloc[-1].to_dict() if not df_240m.empty else {}
                }

                # Pozisyon durumu
                pos_state = self.broker.open_positions.get(sym)

                # Günlük geçmiş veri (Teknik indikatörler için)
                raw_d = yf.download(ticker, period="60d", interval="1d", progress=False)
                if isinstance(raw_d.columns, pd.MultiIndex):
                    raw_d.columns = raw_d.columns.get_level_values(0)
                raw_d = raw_d.reset_index()
                d_col = "Datetime" if "Datetime" in raw_d.columns else "Date"
                daily_df = pd.DataFrame({
                    "timestamp": pd.to_datetime(raw_d[d_col]).dt.tz_localize(None),
                    "open": raw_d["Open"].astype(float),
                    "high": raw_d["High"].astype(float),
                    "low": raw_d["Low"].astype(float),
                    "close": raw_d["Close"].astype(float),
                    "volume": raw_d["Volume"].astype(float) if "Volume" in raw_d.columns else 0.0
                }).dropna().sort_values("timestamp").reset_index(drop=True)

                hourly_proxy = df_240m if not df_240m.empty else df_15m

                # Teknik İcra Değerlendirmesi
                tech_decision = self.executioner.evaluate(
                    symbol=sym,
                    compass_bias=DirectionalBias.BI_DIRECTIONAL if cat in ("EQUITY", "INDEX", "COMMODITY") else DirectionalBias.NEUTRAL,
                    daily_data=daily_df,
                    hourly_data=hourly_proxy,
                    position_state=pos_state,
                    portfolio_nav=self.broker.current_nav,
                    free_margin=self.broker.free_margin
                )

                action = tech_decision.action
                is_entry = action in (ExecutionActionV4.ENTER_LONG, ExecutionActionV4.ENTER_SHORT)
                is_exit = action in (
                    ExecutionActionV4.SCALE_OUT_33,
                    ExecutionActionV4.SCALE_OUT_50,
                    ExecutionActionV4.TIME_STOP_EXIT,
                    ExecutionActionV4.CHANDELIER_STOP_EXIT,
                    ExecutionActionV4.TREND_REVERSAL_EXIT,
                    ExecutionActionV4.FRIDAY_CLOSE_EXIT
                )

                if cb_active and is_entry:
                    logger.warning("🚨 [DEVRE KESİCİ AKTİF] %s giriş emri engellendi: %s", sym, cb_reason)
                elif is_entry or is_exit:
                    order_details = {
                        "symbol": sym,
                        "action": action.value,
                        "lots": tech_decision.target_lots,
                        "current_price": curr_p,
                        "stop_price": tech_decision.stop_price,
                        "rationale": tech_decision.reason,
                        "timestamp": now
                    }
                    exec_record = self.broker.execute_virtual_order(order_details)
                    if exec_record.executed_successfully:
                        executed_trades.append({
                            "symbol": sym,
                            "action": action.value,
                            "lots": exec_record.lots,
                            "price": exec_record.execution_price,
                            "commission": exec_record.commission_try,
                            "pnl": exec_record.realized_pnl_try
                        })
                        logger.info("🎯 [OTOMATİK İCRA] %s %s | %d Lot @ %.2f TL | Kâr/Zarar: %.2f TL",
                                    sym, action.value, exec_record.lots, exec_record.execution_price, exec_record.realized_pnl_try)

                        if exec_record.realized_pnl_try != 0.0:
                            self.db.record_trade({
                                "trade_id": f"TRD_{now.strftime('%Y%m%d%H%M%S')}_{sym}",
                                "symbol": sym,
                                "side": "LONG" if "LONG" in action.value else "SHORT",
                                "lots": exec_record.lots,
                                "entry_price": exec_record.execution_price,
                                "exit_price": curr_p,
                                "entry_time": now.isoformat(),
                                "exit_time": now.isoformat(),
                                "pnl_try": exec_record.realized_pnl_try,
                                "r_multiple": 1.0,
                                "exit_reason": action.value
                            })

            except Exception as e:
                logger.debug("%s sözleşmesi değerlendirilirken hata: %s", sym, e)

        # 4. Açık Pozisyonları ve Sistem Durumunu Senkronize Et
        db_positions = []
        for sym, pos in self.broker.open_positions.items():
            curr_p = self.broker.market_prices.get(sym, pos.entry_price)
            spec = self.config.contracts.get(sym)
            mult = spec.multiplier if spec else 100.0
            pnl = (curr_p - pos.entry_price) * pos.lots * mult if pos.lots > 0 else (pos.entry_price - curr_p) * abs(pos.lots) * mult
            r_mult = pos.get_current_r_multiple(curr_p)
            db_positions.append({
                "symbol": sym,
                "side": "LONG" if pos.lots > 0 else "SHORT",
                "lots": abs(pos.lots),
                "entry_price": pos.entry_price,
                "current_price": curr_p,
                "initial_stop": pos.initial_stop,
                "trailing_stop": pos.trailing_stop,
                "pnl_try": pnl,
                "r_multiple": r_mult,
                "bars_held": pos.bars_held,
                "entry_time": getattr(pos, "entry_time", now.isoformat())
            })
        self.db.sync_active_positions(db_positions)

        # 5. Margin Call Denetimi (Otonom)
        mc_report = self.scheduler.check_margin_call(
            account_equity=self.broker.current_nav,
            active_positions=db_positions,
            custom_check_type="AUTONOMOUS_CYCLE"
        )

        # 6. Seans Sonu ALE Net Nema Hesabı (18:15)
        if now.time() >= time(18, 15) and self.last_ale_eod_date != today_str:
            logger.info("🌙 [18:15 SEANS SONU] Boşta kalan serbest teminata ALE Fonu neması işletiliyor...")
            self.scheduler.calculate_ale_fund_eod(idle_cash=self.broker.free_margin)
            self.last_ale_eod_date = today_str

        # 7. Sistem Durumunu SQLite ve live_market_state.json Dosyasına Yaz
        daily_pnl = self.broker.current_nav - self.risk_manager.state.day_start_nav
        daily_ret_pct = (daily_pnl / self.risk_manager.state.day_start_nav * 100.0) if self.risk_manager.state.day_start_nav > 0 else 0.0

        self.db.record_system_state(
            total_nav=self.broker.current_nav,
            free_margin=self.broker.free_margin,
            daily_pnl=daily_pnl,
            daily_return_pct=daily_ret_pct,
            trading_mode=self.risk_manager.state.trading_mode.value,
            consecutive_losses=self.risk_manager.state.consecutive_losses,
            circuit_breaker_active=cb_active
        )
        self.risk_manager.update_day_boundary(now, self.broker.current_nav)
        curve_pts = self.risk_manager.state.equity_curve
        sma20_c = sum(curve_pts[-20:]) / len(curve_pts[-20:]) if curve_pts else self.broker.current_nav
        self.db.record_equity_point(nav=self.broker.current_nav, sma20=sma20_c, mode=self.risk_manager.state.trading_mode.value)

        # live_market_state.json atomik güncelleme
        state_payload = {
            "metadata": {
                "system": "Autonomous VİOP Live Operator v4.2",
                "synced_at": now.isoformat(),
                "mode": "100% AUTONOMOUS (ZERO MANUAL INTERVENTION)",
                "delay_minutes": 15,
                "supported_timeframes": ["15m", "120m", "240m"],
                "total_contracts": len(self.PORTFOLIO_SYMBOLS),
                "total_nav": round(self.broker.current_nav, 2),
                "free_margin": round(self.broker.free_margin, 2),
                "open_positions_count": len(self.broker.open_positions),
                "executed_trades_this_cycle": len(executed_trades)
            },
            "macro": macro,
            "fintables_stream": stream,
            "ale_fund_nema": ale_rates,
            "contracts": contracts_snapshot,
            "margin_call": mc_report.model_dump(),
            "last_morning_sync": self.last_morning_sync_date
        }
        with open(self.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state_payload, f, ensure_ascii=False, indent=2, default=str)

        logger.info("✓ [OTONOM DÖNGÜ TAMAMLANDI] NAV: %s TL | Serbest Teminat: %s TL | Açık Pozisyon: %d | İcra: %d",
                    f"{self.broker.current_nav:,.2f}", f"{self.broker.free_margin:,.2f}", len(self.broker.open_positions), len(executed_trades))
        return state_payload

    async def start_autonomous_loop(self, interval_seconds: int = 900) -> None:
        """
        Sonsuz otonom döngü (Varsayılan: 15 dakikada 1 tick).
        Kullanıcı hiçbir tuşa basmaz, tüm operasyon arkaplanda kendi kendine yürütülür.
        """
        logger.info("🚀 [OTONOM CANLI OPERATÖR BAŞLATILDI] Periyot: %d saniye (Sıfır Manuel Müdahale Modu)", interval_seconds)
        while True:
            try:
                await self.execute_autonomous_cycle()
            except Exception as exc:
                logger.error("Otonom döngüde beklenmeyen hata (Bot çalışmaya devam ediyor): %s", exc, exc_info=True)
            await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="VİOP Autonomous Live Operator v4.2")
    parser.add_argument("--once", action="store_true", help="Tek bir döngü çalıştır ve çık")
    parser.add_argument("--interval", type=int, default=900, help="Döngü periyodu (saniye, varsayılan: 900 sn = 15 dk)")
    args = parser.parse_args()

    if args.once:
        operator = AutonomousLiveOperator()
        asyncio.run(operator.execute_autonomous_cycle())
    else:
        lock = acquire_operator_lock()
        if not lock:
            print("[BİLGİ] VİOP Otonom Canlı Operatör zaten arkaplanda çalışıyor (İkinci kopya açılmadı).")
            sys.exit(0)
        operator = AutonomousLiveOperator()
        try:
            asyncio.run(operator.start_autonomous_loop(interval_seconds=args.interval))
        finally:
            if lock:
                try:
                    lock.close()
                except Exception:
                    pass
