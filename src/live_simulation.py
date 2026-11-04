"""
Canlı Simülasyon Orkestratörü (Live Simulation Engine - Paper Trading).

Bu modül;
- Canlı Fintables MCP ve TCMB servislerini düzenli aralıklarla dinler,
- v4.0 Anayasası kurallarını (Temel Pusula & Teknik İcra Motoru) işletir,
- Üretilen sinyalleri PaperBroker sanal aracı kurumuna iletir,
- Portföy NAV, serbest teminat, açık pozisyonlar ve icra detaylarını
  'paper_trading.log' dosyasına ve terminale kayıt eder.
"""

import asyncio
from datetime import datetime
import json
import logging
import os
import sys
from typing import Any, Dict, Optional, Tuple
import pandas as pd
import yfinance as yf

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.data.fintables_mcp import FintablesMCPClient
from src.data.global_macro import GlobalMacroClient
from src.data.tcmb_mcp import TCMBMCPClient
from src.execution.paper_broker import PaperBroker
from src.database.db_manager import DatabaseManager
from src.strategy.portfolio_manager import PortfolioRiskManager, TradingMode
from src.strategy.fundamental_compass import (
    AssetChannel,
    CostOfCarryInput,
    DirectionalBias,
    FundamentalCompass,
    MarketMicrostructureInput
)
from src.strategy.orchestrator import StrategyOrchestratorV4
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalDecisionV4,
    TechnicalExecutioner
)

# Logging Yapılandırması (paper_trading.log)
log_file_path = os.path.join(os.path.dirname(__file__), "..", "paper_trading.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("LivePaperSimulation")


class LiveSimulationEngine:
    """
    VİOP v4.0 Sanal Canlı İşlem Motoru (Ali Perşembe 33 Kural & SQLite Destekli).
    """

    def __init__(
        self,
        symbol: str = "F_THYAO",
        underlying_ticker: str = "THYAO.IS",
        channel: AssetChannel = AssetChannel.EQUITY_REAL
    ) -> None:
        self.symbol = symbol
        self.underlying_ticker = underlying_ticker
        self.channel = channel

        # Servisler ve İstemciler
        self.fintables = FintablesMCPClient()
        self.tcmb = TCMBMCPClient()
        self.global_macro = GlobalMacroClient()

        # Kalıcı Veritabanı ve Risk Yöneticisi
        self.db = DatabaseManager()
        self.risk_manager = PortfolioRiskManager(initial_capital=1_000_000.0)

        # Motorlar
        self.broker = PaperBroker(initial_capital=1_000_000.0)
        self.compass = FundamentalCompass()
        self.executioner = TechnicalExecutioner()
        self.orchestrator = StrategyOrchestratorV4(self.compass, self.executioner)

    async def fetch_live_market_data(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Canlı saatlik ve günlük fiyat verilerini çeker.
        """
        # Saatlik veri (60 Gün)
        raw_h = yf.download(self.underlying_ticker, period="60d", interval="1h", progress=False)
        if isinstance(raw_h.columns, pd.MultiIndex):
            raw_h.columns = raw_h.columns.get_level_values(0)
        raw_h = raw_h.reset_index()
        hourly_ts = pd.to_datetime(raw_h["Datetime"]).dt.tz_localize(None)

        hourly_df = pd.DataFrame({
            "timestamp": hourly_ts,
            "open": raw_h["Open"].astype(float),
            "high": raw_h["High"].astype(float),
            "low": raw_h["Low"].astype(float),
            "close": raw_h["Close"].astype(float),
            "volume": raw_h["Volume"].astype(float)
        }).dropna().sort_values("timestamp").reset_index(drop=True)

        # Günlük veri (1 Yıl)
        raw_d = yf.download(self.underlying_ticker, period="1y", interval="1d", progress=False)
        if isinstance(raw_d.columns, pd.MultiIndex):
            raw_d.columns = raw_d.columns.get_level_values(0)
        raw_d = raw_d.reset_index()
        daily_ts = pd.to_datetime(raw_d["Date"]).dt.tz_localize(None)

        daily_df = pd.DataFrame({
            "timestamp": daily_ts,
            "open": raw_d["Open"].astype(float),
            "high": raw_d["High"].astype(float),
            "low": raw_d["Low"].astype(float),
            "close": raw_d["Close"].astype(float),
            "volume": raw_d["Volume"].astype(float)
        }).dropna().sort_values("timestamp").reset_index(drop=True)

        return hourly_df, daily_df

    async def run_single_simulation_cycle(self) -> Dict[str, Any]:
        """
        Tek bir canlı simülasyon döngüsünü (Tick) icra eder.
        API aksamalarına karşı çökmez (try/except korumalı).
        """
        logger.info("--------------------------------------------------------------------------------")
        logger.info(">>> CANLI SİMÜLASYON DÖNGÜSÜ (TICK) BAŞLATILDI: %s <<<", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        try:
            # 1. Canlı Piyasa ve Makro Verileri Çek
            hourly_df, daily_df = await self.fetch_live_market_data()
            current_bar = hourly_df.iloc[-1]
            current_price = float(current_bar["close"])
            logger.info("Piyasa Fiyatı: %s @ %.2f TL | Saatlik Mum: %s", self.symbol, current_price, current_bar["timestamp"])

            # 2. Temel Bilanço ve Makro Bilgileri
            symbol_raw = self.symbol.replace("F_", "")
            fund_data = await self.fintables.fetch_quarterly_financials(symbol_raw)
            policy_rate = await self.tcmb.fetch_policy_rate()
            logger.info("TCMB Politika Faizi: %%%.2f | Bilanço F/K: %.2f", policy_rate, fund_data.pe_ratio or 0.0)

            # 3. Mikroyapı ve Taşıma Maliyeti
            hourly_volume_try = current_price * float(current_bar["volume"])
            micro = MarketMicrostructureInput(
                adv_try=max(80_000_000.0, hourly_volume_try * 8.0),
                open_interest_contracts=25_000
            )
            carry = CostOfCarryInput(implied_irr=0.48, tcmb_funding_rate=policy_rate / 100.0)

            # 4. Portföy Durumu
            current_nav = self.broker.current_nav
            free_margin = self.broker.free_margin
            pos_state = self.broker.open_positions.get(self.symbol)
            logger.info("Sanal Portföy NAV: %s TL | Serbest Teminat: %s TL", f"{current_nav:,.2f}", f"{free_margin:,.2f}")

            # 5. Orkestratör Kararını Üret
            verdict = self.orchestrator.run_strategy_cycle(
                symbol=self.symbol,
                channel=self.channel,
                daily_data=daily_df,
                hourly_data=hourly_df,
                microstructure=micro,
                cost_of_carry=carry,
                portfolio_nav=current_nav,
                free_margin=free_margin,
                position_state=pos_state,
                fundamental_data=fund_data,
                tcmb_policy_rate=policy_rate / 100.0
            )

            logger.info("Temel Pusula Kararı : %s (%s)", verdict.compass_bias.value, verdict.compass_rationale)
            logger.info("Teknik İcra Kararı   : %s (%s)", verdict.technical_decision.action.value, verdict.technical_decision.reason)

            # 6. Sinyal Varsa ve Devre Kesici İzin Veriyorsa Sanal Aracı Kuruma (PaperBroker) İlet
            cb_active, cb_reason = self.risk_manager.check_circuit_breaker()
            action = verdict.technical_decision.action

            is_entry = action in (
                ExecutionActionV4.ENTER_LONG,
                ExecutionActionV4.ENTER_SHORT,
                ExecutionActionV4.ENTER_LONG_B_TYPE,
                ExecutionActionV4.ENTER_SHORT_B_TYPE,
                ExecutionActionV4.ENTER_LONG_A_TYPE,
                ExecutionActionV4.ENTER_SHORT_A_TYPE,
                ExecutionActionV4.ENTER_BREAKAWAY_GAP,
                ExecutionActionV4.PYRAMID_ADD_33
            )

            is_exit = action in (
                ExecutionActionV4.SCALE_OUT_33,
                ExecutionActionV4.SCALE_OUT_50,
                ExecutionActionV4.TIME_STOP_EXIT,
                ExecutionActionV4.CHANDELIER_STOP_EXIT,
                ExecutionActionV4.TREND_REVERSAL_EXIT,
                ExecutionActionV4.FRIDAY_CLOSE_EXIT
            )

            if cb_active and is_entry:
                logger.warning("🚨 Devre kesici AKTİF! Yeni giriş emri engellendi: %s", cb_reason)
            elif is_entry or is_exit:
                order_details = {
                    "symbol": self.symbol,
                    "action": action.value,
                    "lots": verdict.technical_decision.target_lots,
                    "current_price": current_price,
                    "stop_price": verdict.technical_decision.stop_price,
                    "rationale": verdict.technical_decision.reason,
                    "timestamp": datetime.now()
                }
                exec_record = self.broker.execute_virtual_order(order_details)
                # Kapanan işlem varsa trade tablosuna kaydet
                if exec_record.realized_pnl_try != 0.0:
                    self.db.record_trade({
                        "trade_id": f"TRD_{datetime.now().strftime('%Y%m%d%H%M%S')}_{self.symbol}",
                        "symbol": self.symbol,
                        "side": "LONG" if exec_record.action.startswith("ENTER_LONG") else "SHORT",
                        "lots": exec_record.lots,
                        "entry_price": exec_record.execution_price,
                        "exit_price": current_price,
                        "entry_time": datetime.now(),
                        "exit_time": datetime.now(),
                        "pnl_try": exec_record.realized_pnl_try,
                        "r_multiple": 1.0,
                        "exit_reason": action.value
                    })

            # 7. Kalıcı Veritabanı (SQLite) Senkronizasyonu
            daily_pnl = self.broker.current_nav - self.risk_manager.state.day_start_nav
            daily_ret_pct = (daily_pnl / self.risk_manager.state.day_start_nav) * 100.0 if self.risk_manager.state.day_start_nav > 0 else 0.0

            self.db.record_system_state(
                total_nav=self.broker.current_nav,
                free_margin=self.broker.free_margin,
                daily_pnl=daily_pnl,
                daily_return_pct=daily_ret_pct,
                trading_mode=self.risk_manager.state.trading_mode.value,
                consecutive_losses=self.risk_manager.state.consecutive_losses,
                circuit_breaker_active=cb_active
            )

            # Kâr eğrisi noktası
            self.risk_manager.update_day_boundary(datetime.now(), self.broker.current_nav)
            curve_points = self.risk_manager.state.equity_curve
            sma20_curve = sum(curve_points[-20:]) / len(curve_points[-20:]) if curve_points else self.broker.current_nav
            self.db.record_equity_point(
                nav=self.broker.current_nav,
                sma20=sma20_curve,
                mode=self.risk_manager.state.trading_mode.value
            )

            # Açık pozisyonları senkronize et
            db_positions = []
            for sym, pos in self.broker.open_positions.items():
                r_mult = pos.get_current_r_multiple(current_price)
                pnl = (current_price - pos.entry_price) * pos.lots * 100.0
                db_positions.append({
                    "symbol": sym,
                    "side": "LONG" if pos.lots > 0 else "SHORT",
                    "lots": abs(pos.lots),
                    "entry_price": pos.entry_price,
                    "current_price": current_price,
                    "initial_stop": pos.initial_stop,
                    "trailing_stop": pos.trailing_stop,
                    "pnl_try": pnl,
                    "r_multiple": r_mult,
                    "bars_held": pos.bars_held,
                    "entry_time": getattr(pos, "entry_time", datetime.now().isoformat())
                })
            self.db.sync_active_positions(db_positions)

            # Güncel Durum Özeti
            report = {
                "timestamp": datetime.now().isoformat(),
                "symbol": self.symbol,
                "current_price": current_price,
                "compass_bias": verdict.compass_bias.value,
                "technical_action": verdict.technical_decision.action.value,
                "current_nav": round(self.broker.current_nav, 2),
                "free_margin": round(self.broker.free_margin, 2),
                "trading_mode": self.risk_manager.state.trading_mode.value,
                "open_lots": self.broker.open_positions[self.symbol].lots if self.symbol in self.broker.open_positions else 0
            }
            logger.info("Döngü Tamamlandı ve Veritabanı Senkronize Edildi -> %s", json.dumps(report, ensure_ascii=False))
            return report

        except Exception as exc:
            logger.error("Döngü sırasında hata yakalandı (Sistem çökmedi, bekleniyor): %s", exc, exc_info=True)
            return {"status": "error", "message": str(exc)}

    async def start_scheduled_loop(self, interval_seconds: int = 3600, iterations: int = 1) -> None:
        """
        Belirtilen periyotla canlı simülasyon döngüsünü işletir.
        """
        for i in range(iterations):
            await self.run_single_simulation_cycle()
            if i < iterations - 1:
                await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    engine = LiveSimulationEngine(symbol="F_THYAO", underlying_ticker="THYAO.IS")
    # İlk döngüyü (Tick) tek seferlik çalıştır ve doğrula
    asyncio.run(engine.start_scheduled_loop(interval_seconds=1, iterations=1))
