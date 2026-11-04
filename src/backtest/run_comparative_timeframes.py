"""
120-Dakika ve 240-Dakika Karşılaştırmalı VİOP Backtest + Kör Test Motoru
(src/backtest/run_comparative_timeframes.py).

Gereksinimler:
1. Gürültü Önleyici Çoklu Vade: 120m (2 saat) ve 240m (4 saat) barlar
2. Midas Kademeli VİOP İşlem Komisyonu:
   - 0-10M TL: %0.05 (On binde 5)
   - 10-100M TL: %0.02 (On binde 2)
   - 100M+ TL: %0.01 (On binde 1)
3. Akbank ALE Para Piyasası Fonu Net Neması:
   - %48 brüt yıllık nema üzerinden yasal %17.5 stopaj kesintisi ile NET nema hesabı
4. 20 VİOP Sözleşmesi x 4 Varlık Sınıfı (Hisse, Endeks, Emtia, Döviz)
5. Önceki test sonuçları (60m) ile 120m ve 240m sonuçlarının detaylı karşılaştırması
"""

import asyncio
from datetime import datetime, timedelta
import json
import os
import sys
from typing import Any, Dict, List, Tuple
import pandas as pd
import yfinance as yf

# UTF-8 terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.backtest.event_driven_tester import BacktestTearsheet, EventDrivenBacktester
from src.backtest.generate_100k_backtest import calculate_ale_fund_performance
from src.data.schemas import FundamentalData
from src.strategy.fundamental_compass import AssetChannel, DirectionalBias


async def run_comparative_simulation():
    print("=" * 100)
    print("  VİOP ALGOTRADE v4.0 - 120 DAKİKA vs 240 DAKİKA KARŞILAŞTIRMALI BACKTEST & KÖR TEST")
    print("  (Midas Kademeli Komisyon Tarifesi + Akbank ALE Fonu %17.5 Stopaj Kesintili Net Kasa)")
    print("=" * 100)

    initial_capital = 150_000.0
    split_date = datetime(2025, 10, 1)

    # Önceki test sonuçlarını (60m Baseline) yükle
    db_dir = os.path.join(os.path.dirname(__file__), "..", "database")
    prev_file = os.path.join(db_dir, "backtest_results_150k.json")
    prev_results = {}
    if os.path.exists(prev_file):
        try:
            with open(prev_file, "r", encoding="utf-8") as f:
                prev_data = json.load(f)
                prev_results = prev_data.get("assets", {})
        except Exception as e:
            print(f"[!] Önceki sonuçlar yüklenirken uyarı: {e}")

    # 4 Varlık Sınıfı x 5 Sözleşme = 20 VİOP Sözleşmesi
    assets_config = [
        # 1. HİSSE PAY VADELİ (5 Adet)
        {"symbol": "F_THYAO", "ticker_yf": "THYAO.IS", "channel": AssetChannel.EQUITY_REAL, "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 6500.0},
        {"symbol": "F_AKBNK", "ticker_yf": "AKBNK.IS", "channel": AssetChannel.EQUITY_BANK, "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 2200.0},
        {"symbol": "F_GARAN", "ticker_yf": "GARAN.IS", "channel": AssetChannel.EQUITY_BANK, "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 3800.0},
        {"symbol": "F_EREGL", "ticker_yf": "EREGL.IS", "channel": AssetChannel.EQUITY_REAL, "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 1800.0},
        {"symbol": "F_TUPRS", "ticker_yf": "TUPRS.IS", "channel": AssetChannel.EQUITY_REAL, "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 4500.0},

        # 2. ENDEKS VADELİ (5 Adet)
        {"symbol": "F_XU030", "ticker_yf": "XU030.IS", "channel": AssetChannel.INDEX, "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 22000.0},
        {"symbol": "F_XU100", "ticker_yf": "XU100.IS", "channel": AssetChannel.INDEX, "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 20000.0},
        {"symbol": "F_XLBNK", "ticker_yf": "XBANK.IS", "channel": AssetChannel.INDEX, "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 18000.0},
        {"symbol": "F_XUSIN", "ticker_yf": "XUSIN.IS", "channel": AssetChannel.INDEX, "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 18000.0},
        {"symbol": "F_XGMYO", "ticker_yf": "XGMYO.IS", "channel": AssetChannel.INDEX, "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 15000.0},

        # 3. EMTİA / KIYMETLİ MADEN (5 Adet)
        {"symbol": "F_XAUUSD", "ticker_yf": "GC=F", "channel": AssetChannel.COMMODITY, "category": "Emtia", "contract_multiplier": 1.0, "initial_margin_try": 6000.0},
        {"symbol": "F_XAGUSD", "ticker_yf": "SI=F", "channel": AssetChannel.COMMODITY, "category": "Emtia", "contract_multiplier": 10.0, "initial_margin_try": 3000.0},
        {"symbol": "F_BRENT", "ticker_yf": "BZ=F", "channel": AssetChannel.COMMODITY, "category": "Emtia", "contract_multiplier": 10.0, "initial_margin_try": 3500.0},
        {"symbol": "F_PLAT", "ticker_yf": "PL=F", "channel": AssetChannel.COMMODITY, "category": "Emtia", "contract_multiplier": 1.0, "initial_margin_try": 3000.0},
        {"symbol": "F_COPPER", "ticker_yf": "HG=F", "channel": AssetChannel.COMMODITY, "category": "Emtia", "contract_multiplier": 100.0, "initial_margin_try": 4000.0},

        # 4. DÖVİZ VADELİ (5 Adet)
        {"symbol": "F_USDTRY", "ticker_yf": "TRY=X", "channel": AssetChannel.FX, "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 3500.0},
        {"symbol": "F_EURTRY", "ticker_yf": "EURTRY=X", "channel": AssetChannel.FX, "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 4000.0},
        {"symbol": "F_EURUSD", "ticker_yf": "EURUSD=X", "channel": AssetChannel.FX, "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 3500.0},
        {"symbol": "F_GBPTRY", "ticker_yf": "GBPTRY=X", "channel": AssetChannel.FX, "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 4500.0},
        {"symbol": "F_DXY", "ticker_yf": "DX-Y.NYB", "channel": AssetChannel.FX, "category": "Döviz", "contract_multiplier": 100.0, "initial_margin_try": 3000.0}
    ]

    comparative_report = {
        "metadata": {
            "title": "VİOP v4.0 - 120m vs 240m Timeframe ve Midas Kademeli Komisyon Analizi",
            "initial_capital": initial_capital,
            "generated_at": datetime.now().isoformat(),
            "in_sample_period": "Ekim 2023 - Ekim 2025 (2 Yıl Saatlik / 3 Yıl Günlük)",
            "out_of_sample_period": "Ekim 2025 - Ekim 2026 (1 Yıl Kör Test)",
            "withholding_tax_pct": 0.175,
            "commission_structure": "Midas Tiered: 0-10M %0.05, 10-100M %0.02, 100M+ %0.01",
            "ale_repo_rate_annual": 0.48
        },
        "assets": {}
    }

    fund_data_default = FundamentalData(
        symbol="VIOP",
        as_of_date=datetime(2026, 6, 30),
        announced_at=datetime(2026, 8, 5, 18, 30),
        source="PRO_DATA",
        period_year=2026,
        period_quarter=2,
        pe_ratio=5.2,
        pb_ratio=1.1,
        ev_ebitda=4.5,
        roe=0.32,
        roa=0.10,
        net_profit_margin=0.20,
        net_profit_try=35_000_000_000.0,
        revenue_try=160_000_000_000.0,
        ebitda_try=42_000_000_000.0,
        equity_try=180_000_000_000.0
    )

    for cfg in assets_config:
        sym = cfg["symbol"]
        ticker = cfg["ticker_yf"]
        cat = cfg["category"]
        print(f"\n[*] [{cat}] {sym} ({ticker}) verileri çekiliyor ve 120m / 240m barlara resample ediliyor...")

        try:
            raw_h = yf.download(ticker, period="730d", interval="1h", progress=False)
            if isinstance(raw_h.columns, pd.MultiIndex):
                raw_h.columns = raw_h.columns.get_level_values(0)
            raw_h = raw_h.reset_index()
            t_col_h = "Datetime" if "Datetime" in raw_h.columns else "Date"
            hourly_ts = pd.to_datetime(raw_h[t_col_h]).dt.tz_localize(None)

            hourly_df = pd.DataFrame({
                "timestamp": hourly_ts,
                "open": raw_h["Open"].astype(float),
                "high": raw_h["High"].astype(float),
                "low": raw_h["Low"].astype(float),
                "close": raw_h["Close"].astype(float),
                "volume": raw_h["Volume"].astype(float) if "Volume" in raw_h.columns else 0.0
            }).dropna().sort_values("timestamp").reset_index(drop=True)

            raw_d = yf.download(ticker, period="5y", interval="1d", progress=False)
            if isinstance(raw_d.columns, pd.MultiIndex):
                raw_d.columns = raw_d.columns.get_level_values(0)
            raw_d = raw_d.reset_index()
            t_col_d = "Datetime" if "Datetime" in raw_d.columns else "Date"
            daily_ts = pd.to_datetime(raw_d[t_col_d]).dt.tz_localize(None)

            daily_df = pd.DataFrame({
                "timestamp": daily_ts,
                "open": raw_d["Open"].astype(float),
                "high": raw_d["High"].astype(float),
                "low": raw_d["Low"].astype(float),
                "close": raw_d["Close"].astype(float),
                "volume": raw_d["Volume"].astype(float) if "Volume" in raw_d.columns else 0.0
            }).dropna().sort_values("timestamp").reset_index(drop=True)

            if hourly_df.empty or daily_df.empty:
                print(f"    [!] {sym} için veri bulunamadı, atlanıyor.")
                continue

            in_hourly = hourly_df[hourly_df["timestamp"] < split_date].copy().reset_index(drop=True)
            in_daily = daily_df[daily_df["timestamp"] < split_date].copy().reset_index(drop=True)

            out_hourly = hourly_df[hourly_df["timestamp"] >= split_date].copy().reset_index(drop=True)
            out_daily = daily_df.copy().reset_index(drop=True)

            # Önceki baseline sonuçları
            p_asset = prev_results.get(sym, {})
            p_in = p_asset.get("in_sample", {})
            p_out = p_asset.get("out_of_sample", {})

            # -------------------------------------------------------------
            # A. 120-DAKİKALIK SİMÜLASYON
            # -------------------------------------------------------------
            backtester_120 = EventDrivenBacktester(initial_capital=initial_capital, use_midas_commission=True)
            ts_in_120 = backtester_120.run_backtest(
                symbol=sym,
                hourly_df=in_hourly,
                daily_df=in_daily,
                fundamental_data=fund_data_default,
                channel=cfg["channel"],
                contract_multiplier=cfg["contract_multiplier"],
                initial_margin_per_contract=cfg["initial_margin_try"],
                timeframe_minutes=120
            )
            ale_in_120 = calculate_ale_fund_performance(
                hourly_df=in_hourly,
                trades=ts_in_120.trades,
                initial_capital=initial_capital,
                annual_rate=0.48,
                initial_margin_per_contract=cfg["initial_margin_try"],
                withholding_tax_pct=0.175
            )

            ts_out_120 = backtester_120.run_backtest(
                symbol=sym,
                hourly_df=out_hourly,
                daily_df=out_daily,
                fundamental_data=fund_data_default,
                channel=cfg["channel"],
                contract_multiplier=cfg["contract_multiplier"],
                initial_margin_per_contract=cfg["initial_margin_try"],
                timeframe_minutes=120
            )
            ale_out_120 = calculate_ale_fund_performance(
                hourly_df=out_hourly,
                trades=ts_out_120.trades,
                initial_capital=initial_capital,
                annual_rate=0.48,
                initial_margin_per_contract=cfg["initial_margin_try"],
                withholding_tax_pct=0.175
            )

            # -------------------------------------------------------------
            # B. 240-DAKİKALIK SİMÜLASYON
            # -------------------------------------------------------------
            backtester_240 = EventDrivenBacktester(initial_capital=initial_capital, use_midas_commission=True)
            ts_in_240 = backtester_240.run_backtest(
                symbol=sym,
                hourly_df=in_hourly,
                daily_df=in_daily,
                fundamental_data=fund_data_default,
                channel=cfg["channel"],
                contract_multiplier=cfg["contract_multiplier"],
                initial_margin_per_contract=cfg["initial_margin_try"],
                timeframe_minutes=240
            )
            ale_in_240 = calculate_ale_fund_performance(
                hourly_df=in_hourly,
                trades=ts_in_240.trades,
                initial_capital=initial_capital,
                annual_rate=0.48,
                initial_margin_per_contract=cfg["initial_margin_try"],
                withholding_tax_pct=0.175
            )

            ts_out_240 = backtester_240.run_backtest(
                symbol=sym,
                hourly_df=out_hourly,
                daily_df=out_daily,
                fundamental_data=fund_data_default,
                channel=cfg["channel"],
                contract_multiplier=cfg["contract_multiplier"],
                initial_margin_per_contract=cfg["initial_margin_try"],
                timeframe_minutes=240
            )
            ale_out_240 = calculate_ale_fund_performance(
                hourly_df=out_hourly,
                trades=ts_out_240.trades,
                initial_capital=initial_capital,
                annual_rate=0.48,
                initial_margin_per_contract=cfg["initial_margin_try"],
                withholding_tax_pct=0.175
            )

            def pack_metrics(ts: BacktestTearsheet, ale: Dict) -> Dict:
                return {
                    "final_capital": round(ts.final_capital, 2),
                    "trade_net_pnl": round(ts.total_net_pnl, 2),
                    "ale_net_income": ale["ale_total_income_try"],
                    "ale_tax_paid": ale["ale_tax_paid_try"],
                    "consolidated_nav": ale["consolidated_nav_try"],
                    "total_yield_pct": ale["total_yield_pct"],
                    "total_trades": ts.total_trades,
                    "win_rate_pct": ts.win_rate_pct,
                    "max_drawdown_pct": ts.max_drawdown_pct,
                    "profit_factor": ts.profit_factor,
                    "total_commissions": ts.total_commissions,
                    "trades": [
                        {
                            "id": tr.trade_id, "side": tr.side, "pnl": tr.realized_pnl,
                            "entry": tr.entry_price, "exit": tr.exit_price, "lots": tr.lots,
                            "comm": tr.commission_paid, "reason": tr.exit_reason
                        }
                        for tr in ts.trades
                    ]
                }

            comparative_report["assets"][sym] = {
                "category": cat,
                "ticker": ticker,
                "contract_multiplier": cfg["contract_multiplier"],
                "initial_margin": cfg["initial_margin_try"],
                "in_sample": {
                    "baseline_60m": {
                        "trade_net_pnl": p_in.get("total_net_pnl", 0.0),
                        "ale_income": p_in.get("ale_income_try", 0.0),
                        "consolidated_nav": p_in.get("consolidated_nav_try", initial_capital),
                        "total_trades": p_in.get("total_trades", 0),
                        "win_rate_pct": p_in.get("win_rate_pct", 0.0)
                    },
                    "timeframe_120m": pack_metrics(ts_in_120, ale_in_120),
                    "timeframe_240m": pack_metrics(ts_in_240, ale_in_240)
                },
                "out_of_sample": {
                    "baseline_60m": {
                        "trade_net_pnl": p_out.get("total_net_pnl", 0.0),
                        "ale_income": p_out.get("ale_income_try", 0.0),
                        "consolidated_nav": p_out.get("consolidated_nav_try", initial_capital),
                        "total_trades": p_out.get("total_trades", 0),
                        "win_rate_pct": p_out.get("win_rate_pct", 0.0)
                    },
                    "timeframe_120m": pack_metrics(ts_out_120, ale_out_120),
                    "timeframe_240m": pack_metrics(ts_out_240, ale_out_240)
                }
            }

            print(f"    ✓ {sym} In-Sample  : [60m NAV: {p_in.get('consolidated_nav_try', 0):,.0f} TL] -> [120m NAV: {ale_in_120['consolidated_nav_try']:,.0f} TL (Tr:{ts_in_120.total_trades})] -> [240m NAV: {ale_in_240['consolidated_nav_try']:,.0f} TL (Tr:{ts_in_240.total_trades})]")
            print(f"    ✓ {sym} Kör Test   : [60m NAV: {p_out.get('consolidated_nav_try', 0):,.0f} TL] -> [120m NAV: {ale_out_120['consolidated_nav_try']:,.0f} TL (Tr:{ts_out_120.total_trades})] -> [240m NAV: {ale_out_240['consolidated_nav_try']:,.0f} TL (Tr:{ts_out_240.total_trades})]")

        except Exception as e:
            print(f"    [!] {sym} hatası: {e}")

    # Raporu kaydet
    out_file = os.path.join(db_dir, "comparative_timeframe_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(comparative_report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 100)
    print(f"  [OK] 120m ve 240m Karşılaştırma Raporu Başarıyla Kaydedildi -> {out_file}")
    print("=" * 100)
    return comparative_report


if __name__ == "__main__":
    asyncio.run(run_comparative_simulation())
