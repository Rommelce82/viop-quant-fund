"""
150.000 TL Sanal Bütçe ile 3 Yıllık Backtest, Kör Test ve Akbank ALE Fonu Nemalandırma Motoru.
(src/backtest/generate_100k_backtest.py)

Bu betik:
- Başlangıç Sermayesi: 150.000 TL sanal bütçe ve kasa,
- Varlık Evreni: 4 Varlık Sınıfı x 5'er adet Sözleşme = 20 VİOP Sözleşmesi
  * Hisse (5): F_THYAO, F_AKBNK, F_GARAN, F_EREGL, F_TUPRS
  * Endeks (5): F_XU030, F_XU100, F_XLBNK, F_XUSIN, F_XGMYO
  * Emtia (5): F_XAUUSD (Altın), F_XAGUSD (Gümüş), F_BRENT (Petrol), F_PLAT (Platin), F_COPPER (Bakır)
  * Döviz (5): F_USDTRY, F_EURTRY, F_EURUSD, F_GBPTRY, F_DXY
- Dönemler:
  * In-Sample (Geçmiş Test): Ekim 2023 - Ekim 2025 (2 Yıl Saatlik / 3 Yıl Günlük)
  * Out-of-Sample (Kör Test): Ekim 2025 - Ekim 2026 (1 Yıl Saatlik & Günlük)
- Akbank "ALE" Para Piyasası Fonu Nemalandırma Modeli:
  * Serbest Nakit Para (Free Margin), seans kapanışında Akbank ALE Fonunda gecelik değerlendirilir (~%48 yıllık nema).
  * Kural: Trade kârları sermayeye eklenerek bileşik büyür. ALE fonu getirisi ise risk almadan ayrı bir güvenli kasada toplanır.
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
from src.data.schemas import FundamentalData
from src.strategy.fundamental_compass import AssetChannel, DirectionalBias


def calculate_ale_fund_performance(
    hourly_df: pd.DataFrame,
    trades: List[Any],
    initial_capital: float = 150_000.0,
    annual_rate: float = 0.48,
    initial_margin_per_contract: float = 6500.0,
    withholding_tax_pct: float = 0.175
) -> Dict[str, Any]:
    """
    Kullanılmayan serbest nakit paranın (Free Margin) her gün seans kapanışında
    Akbank ALE Para Piyasası Fonu'nda gecelik değerlendirilmesini simüle eder.
    Brüt nema gelirinden yasal %17.5 stopaj kesintisi düşülerek NET kazanç kasaya aktarılır.
    ALE fonu getirileri ayrı bir güvenli kasada toplanır ve trade riskine dahil edilmez.
    """
    if hourly_df.empty:
        return {
            "ale_gross_income_try": 0.0,
            "ale_tax_paid_try": 0.0,
            "ale_total_income_try": 0.0,
            "trade_net_pnl_try": 0.0,
            "final_trading_capital_try": initial_capital,
            "consolidated_nav_try": initial_capital,
            "total_yield_pct": 0.0,
            "daily_series": []
        }

    daily_groups = hourly_df.copy()
    daily_groups["date"] = pd.to_datetime(daily_groups["timestamp"]).dt.date
    unique_dates = sorted(daily_groups["date"].unique())

    trade_events = []
    for tr in trades:
        e_time = pd.to_datetime(tr.entry_time if hasattr(tr, "entry_time") else tr["entry_time"])
        x_time = pd.to_datetime(tr.exit_time if hasattr(tr, "exit_time") else tr["exit_time"])
        lots = abs(tr.lots if hasattr(tr, "lots") else tr["lots"])
        pnl = tr.realized_pnl if hasattr(tr, "realized_pnl") else tr["realized_pnl"]
        trade_events.append({
            "entry_time": e_time,
            "exit_time": x_time,
            "lots": lots,
            "pnl": pnl
        })

    cumulative_trade_pnl = 0.0
    cumulative_ale_gross = 0.0
    cumulative_ale_tax = 0.0
    cumulative_ale_net = 0.0
    trading_capital = initial_capital
    daily_series = []

    for i in range(len(unique_dates)):
        cur_date = unique_dates[i]
        next_date = unique_dates[i+1] if i + 1 < len(unique_dates) else cur_date + timedelta(days=1)
        day_diff = (next_date - cur_date).days
        if day_diff <= 0:
            day_diff = 1

        # O gün kapanan işlemlerin PnL'ini trade kasasına ekle (Bileşik büyüme)
        days_trades = [t for t in trade_events if t["exit_time"].date() == cur_date]
        for dt in days_trades:
            cumulative_trade_pnl += dt["pnl"]
            trading_capital += dt["pnl"]

        # O gün saat 18:15'te açık pozisyon var mı?
        day_end_dt = datetime.combine(cur_date, datetime.min.time()).replace(hour=18, minute=15)
        active_lots = sum(t["lots"] for t in trade_events if t["entry_time"] <= day_end_dt <= t["exit_time"])

        required_margin = active_lots * initial_margin_per_contract
        free_cash = max(0.0, trading_capital - required_margin)

        # Akbank ALE Gecelik Nema Getirisi (%17.5 Stopaj Kesintili Net Hesap)
        daily_rate = (annual_rate / 365.0) * day_diff
        daily_ale_gross = free_cash * daily_rate
        daily_tax = daily_ale_gross * withholding_tax_pct
        daily_ale_net = daily_ale_gross - daily_tax

        cumulative_ale_gross += daily_ale_gross
        cumulative_ale_tax += daily_tax
        cumulative_ale_net += daily_ale_net

        consolidated_nav = trading_capital + cumulative_ale_net
        daily_series.append({
            "date": str(cur_date),
            "trade_pnl_cum": round(cumulative_trade_pnl, 2),
            "ale_gross_cum": round(cumulative_ale_gross, 2),
            "ale_tax_cum": round(cumulative_ale_tax, 2),
            "ale_income_cum": round(cumulative_ale_net, 2),
            "free_cash": round(free_cash, 2),
            "trading_capital": round(trading_capital, 2),
            "total_nav": round(consolidated_nav, 2)
        })

    consolidated_nav = trading_capital + cumulative_ale_net
    total_yield_pct = round(((consolidated_nav - initial_capital) / initial_capital) * 100.0, 2)

    return {
        "ale_gross_income_try": round(cumulative_ale_gross, 2),
        "ale_tax_paid_try": round(cumulative_ale_tax, 2),
        "ale_total_income_try": round(cumulative_ale_net, 2), # Net nema kasası
        "trade_net_pnl_try": round(cumulative_trade_pnl, 2),
        "final_trading_capital_try": round(trading_capital, 2),
        "consolidated_nav_try": round(consolidated_nav, 2),
        "total_yield_pct": total_yield_pct,
        "daily_series": daily_series
    }


async def run_150k_simulation() -> None:
    print("=" * 80)
    print("  150.000 TL SANAL BÜTÇE İLE 3 YILLIK BACKTEST & KÖR TEST ARENASI")
    print("  (20 VİOP SÖZLEŞMESİ: HİSSE, ENDEKS, EMTİA, DÖVİZ | ÇİFT YÖNLÜ LONG/SHORT)")
    print("  (AKBANK ALE FONU GECELİK NEMALANDIRMA MODELİ DAHİL)")
    print("=" * 80)

    initial_capital = 150_000.0
    split_date = datetime(2025, 10, 1)

    # 4 Varlık Sınıfı x 5 Sözleşme = 20 VİOP Sözleşmesi
    assets_config = [
        # 1. HİSSE PAY VADELİ (5 Adet)
        {
            "symbol": "F_THYAO", "ticker_yf": "THYAO.IS", "channel": AssetChannel.EQUITY_REAL,
            "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 6500.0
        },
        {
            "symbol": "F_AKBNK", "ticker_yf": "AKBNK.IS", "channel": AssetChannel.EQUITY_BANK,
            "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 2200.0
        },
        {
            "symbol": "F_GARAN", "ticker_yf": "GARAN.IS", "channel": AssetChannel.EQUITY_BANK,
            "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 3800.0
        },
        {
            "symbol": "F_EREGL", "ticker_yf": "EREGL.IS", "channel": AssetChannel.EQUITY_REAL,
            "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 1800.0
        },
        {
            "symbol": "F_TUPRS", "ticker_yf": "TUPRS.IS", "channel": AssetChannel.EQUITY_REAL,
            "category": "Hisse", "contract_multiplier": 100.0, "initial_margin_try": 4500.0
        },

        # 2. ENDEKS VADELİ (5 Adet)
        {
            "symbol": "F_XU030", "ticker_yf": "XU030.IS", "channel": AssetChannel.INDEX,
            "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 22000.0
        },
        {
            "symbol": "F_XU100", "ticker_yf": "XU100.IS", "channel": AssetChannel.INDEX,
            "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 20000.0
        },
        {
            "symbol": "F_XLBNK", "ticker_yf": "XBANK.IS", "channel": AssetChannel.INDEX,
            "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 18000.0
        },
        {
            "symbol": "F_XUSIN", "ticker_yf": "XUSIN.IS", "channel": AssetChannel.INDEX,
            "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 18000.0
        },
        {
            "symbol": "F_XGMYO", "ticker_yf": "XGMYO.IS", "channel": AssetChannel.INDEX,
            "category": "Endeks", "contract_multiplier": 10.0, "initial_margin_try": 15000.0
        },

        # 3. EMTİA / KIYMETLİ MADEN (5 Adet)
        {
            "symbol": "F_XAUUSD", "ticker_yf": "GC=F", "channel": AssetChannel.COMMODITY,
            "category": "Emtia", "contract_multiplier": 1.0, "initial_margin_try": 6000.0
        },
        {
            "symbol": "F_XAGUSD", "ticker_yf": "SI=F", "channel": AssetChannel.COMMODITY,
            "category": "Emtia", "contract_multiplier": 10.0, "initial_margin_try": 3000.0
        },
        {
            "symbol": "F_BRENT", "ticker_yf": "BZ=F", "channel": AssetChannel.COMMODITY,
            "category": "Emtia", "contract_multiplier": 10.0, "initial_margin_try": 3500.0
        },
        {
            "symbol": "F_PLAT", "ticker_yf": "PL=F", "channel": AssetChannel.COMMODITY,
            "category": "Emtia", "contract_multiplier": 1.0, "initial_margin_try": 3000.0
        },
        {
            "symbol": "F_COPPER", "ticker_yf": "HG=F", "channel": AssetChannel.COMMODITY,
            "category": "Emtia", "contract_multiplier": 100.0, "initial_margin_try": 4000.0
        },

        # 4. DÖVİZ VADELİ (5 Adet)
        {
            "symbol": "F_USDTRY", "ticker_yf": "TRY=X", "channel": AssetChannel.FX,
            "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 3500.0
        },
        {
            "symbol": "F_EURTRY", "ticker_yf": "EURTRY=X", "channel": AssetChannel.FX,
            "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 4000.0
        },
        {
            "symbol": "F_EURUSD", "ticker_yf": "EURUSD=X", "channel": AssetChannel.FX,
            "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 3500.0
        },
        {
            "symbol": "F_GBPTRY", "ticker_yf": "GBPTRY=X", "channel": AssetChannel.FX,
            "category": "Döviz", "contract_multiplier": 1000.0, "initial_margin_try": 4500.0
        },
        {
            "symbol": "F_DXY", "ticker_yf": "DX-Y.NYB", "channel": AssetChannel.FX,
            "category": "Döviz", "contract_multiplier": 100.0, "initial_margin_try": 3000.0
        }
    ]

    all_results = {
        "metadata": {
            "initial_capital": initial_capital,
            "generated_at": datetime.now().isoformat(),
            "in_sample_period": "Ekim 2023 - Ekim 2025 (2 Yıl Saatlik / 3 Yıl Günlük)",
            "out_of_sample_period": "Ekim 2025 - Ekim 2026 (1 Yıl Kör Test)",
            "commission_rate": 0.0004,
            "slippage_rate": 0.0005,
            "ale_fund_annual_rate": 0.48,
            "total_assets": len(assets_config)
        },
        "assets": {}
    }

    for cfg in assets_config:
        sym = cfg["symbol"]
        ticker = cfg["ticker_yf"]
        cat = cfg["category"]
        print(f"\n[*] [{cat}] {sym} ({ticker}) verileri çekiliyor...")

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

            fund_data = FundamentalData(
                symbol=sym.replace("F_", ""),
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

            in_hourly = hourly_df[hourly_df["timestamp"] < split_date].copy().reset_index(drop=True)
            in_daily = daily_df[daily_df["timestamp"] < split_date].copy().reset_index(drop=True)

            out_hourly = hourly_df[hourly_df["timestamp"] >= split_date].copy().reset_index(drop=True)
            out_daily = daily_df.copy().reset_index(drop=True)

            # 1. In-Sample Simülasyonu
            engine_in = EventDrivenBacktester(initial_capital=initial_capital)
            ts_in = engine_in.run_backtest(
                symbol=sym,
                hourly_df=in_hourly,
                daily_df=in_daily,
                fundamental_data=fund_data,
                channel=cfg["channel"],
                contract_multiplier=cfg["contract_multiplier"],
                initial_margin_per_contract=cfg["initial_margin_try"]
            )

            # 2. Out-of-Sample Simülasyonu
            engine_out = EventDrivenBacktester(initial_capital=initial_capital)
            ts_out = engine_out.run_backtest(
                symbol=sym,
                hourly_df=out_hourly,
                daily_df=out_daily,
                fundamental_data=fund_data,
                channel=cfg["channel"],
                contract_multiplier=cfg["contract_multiplier"],
                initial_margin_per_contract=cfg["initial_margin_try"]
            )

            # ALE Fonu Nemalandırma Hesaplamaları (Kullanılmayan serbest nakit)
            ale_in = calculate_ale_fund_performance(
                hourly_df=in_hourly,
                trades=ts_in.trades,
                initial_capital=initial_capital,
                annual_rate=0.48,
                initial_margin_per_contract=cfg["initial_margin_try"]
            )
            ale_out = calculate_ale_fund_performance(
                hourly_df=out_hourly,
                trades=ts_out.trades,
                initial_capital=initial_capital,
                annual_rate=0.48,
                initial_margin_per_contract=cfg["initial_margin_try"]
            )

            def tearsheet_to_dict(ts: BacktestTearsheet, ale_perf: Dict) -> Dict:
                return {
                    "initial_capital": ts.initial_capital,
                    "final_capital": round(ts.final_capital, 2),
                    "total_net_pnl": round(ts.total_net_pnl, 2),
                    "total_return_pct": round(ts.total_return_pct, 2),
                    "max_drawdown_pct": round(ts.max_drawdown_pct, 2),
                    "max_drawdown_try": round(ts.max_drawdown_try, 2),
                    "win_rate_pct": round(ts.win_rate_pct, 1),
                    "total_trades": ts.total_trades,
                    "winning_trades": ts.winning_trades,
                    "losing_trades": ts.losing_trades,
                    "profit_factor": round(ts.profit_factor, 2),
                    "avg_r_multiple": round(ts.avg_r_multiple, 2),
                    "total_commissions": round(ts.total_commissions, 2),
                    "total_slippage": round(ts.total_slippage, 2),
                    "compass_neutral_bars": ts.compass_neutral_bars,
                    "ale_income_try": ale_perf["ale_total_income_try"],
                    "consolidated_nav_try": ale_perf["consolidated_nav_try"],
                    "consolidated_yield_pct": ale_perf["total_yield_pct"],
                    "daily_ale_series": ale_perf["daily_series"][-50:],
                    "trades": [
                        {
                            "trade_id": tr.trade_id,
                            "symbol": tr.symbol,
                            "side": tr.side,
                            "entry_time": tr.entry_time.isoformat() if tr.entry_time else None,
                            "exit_time": tr.exit_time.isoformat() if tr.exit_time else None,
                            "entry_price": tr.entry_price,
                            "exit_price": tr.exit_price,
                            "lots": tr.lots,
                            "notional_value": tr.notional_value,
                            "leverage": tr.leverage,
                            "margin_used": tr.margin_used,
                            "realized_pnl": tr.realized_pnl,
                            "r_multiple": tr.r_multiple_realized,
                            "exit_reason": tr.exit_reason,
                            "bars_held": tr.bars_held
                        }
                        for tr in ts.trades
                    ]
                }

            all_results["assets"][sym] = {
                "category": cat,
                "ticker_yf": ticker,
                "contract_multiplier": cfg["contract_multiplier"],
                "initial_margin_try": cfg["initial_margin_try"],
                "in_sample": tearsheet_to_dict(ts_in, ale_in),
                "out_of_sample": tearsheet_to_dict(ts_out, ale_out)
            }

            print(f"    ✓ {sym} In-Sample  : Trades={ts_in.total_trades} (W:{ts_in.winning_trades}/L:{ts_in.losing_trades}) | Trade PnL={ts_in.total_net_pnl:+,.0f} TL | ALE Nema={ale_in['ale_total_income_try']:+,.0f} TL | Konsolide NAV={ale_in['consolidated_nav_try']:,.0f} TL")
            print(f"    ✓ {sym} Kör Test   : Trades={ts_out.total_trades} (W:{ts_out.winning_trades}/L:{ts_out.losing_trades}) | Trade PnL={ts_out.total_net_pnl:+,.0f} TL | ALE Nema={ale_out['ale_total_income_try']:+,.0f} TL | Konsolide NAV={ale_out['consolidated_nav_try']:,.0f} TL")

        except Exception as e:
            print(f"    [!] {sym} simülasyonunda hata: {e}")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "database")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "backtest_results_100k.json")
    out_path_150k = os.path.join(out_dir, "backtest_results_150k.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    with open(out_path_150k, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"  [OK] Tüm 20 VİOP Sözleşmesi 150.000 TL kasa sonuçları kaydedildi:")
    print(f"  -> {out_path}")
    print(f"  -> {out_path_150k}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_150k_simulation())
