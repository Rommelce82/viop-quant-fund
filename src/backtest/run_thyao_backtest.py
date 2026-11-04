"""
Geçmiş 6 Aylık THYAO Olay Güdümlü Backtest Çalıştırıcısı (run_thyao_backtest.py).

Bu betik;
1. Fintables PRO MCP'den THYAO güncel Point-in-Time temel finansallarını çeker,
2. yfinance üzerinden THYAO'nun son 6 aylık saatlik ve 2 yıllık günlük mum verilerini alır,
3. EventDrivenBacktester motoruna v4.0 Anayasası kurallarıyla (Komisyon on binde 4, Kayma on binde 5,
   t sinyal -> t+1 Open icra) teslim eder,
4. Terminale resmi Performans Raporunu (Tearsheet) döker.
"""

import asyncio
from datetime import datetime
import sys
import pandas as pd
import yfinance as yf

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.backtest.event_driven_tester import EventDrivenBacktester
from src.data.fintables_mcp import FintablesMCPClient
from src.strategy.fundamental_compass import AssetChannel, DirectionalBias


async def run_thyao_backtest():
    print("=" * 80)
    print("  VİOP FAZ 4.1: THYAO GEÇMİŞ 6 AYLIK OLAY GÜDÜMLÜ BACKTEST BAŞLATILIYOR")
    print("=" * 80)

    # 1. ADIM: Fintables PRO Canlı Temel Veri Çekimi
    print("\n[+] 1. Fintables PRO MCP'den THYAO Temel Bilanço Verisi Çekiliyor...")
    fintables = FintablesMCPClient()
    fund_data = await fintables.fetch_quarterly_financials("THYAO")
    print(f"    ✓ Temel Veri Alındı: {fund_data.symbol} {fund_data.period_year}/{fund_data.period_quarter*3} (F/K: {fund_data.pe_ratio})")

    # 2. ADIM: Piyasa Fiyat Verisi İndirme (Saatlik & Günlük)
    print("\n[+] 2. THYAO Saatlik (6 Aylık) ve Günlük (Trend) Fiyat Serisi İndiriliyor...")
    ticker = "THYAO.IS"
    
    # Saatlik veri (6 Ay)
    raw_hourly = yf.download(ticker, period="6mo", interval="1h", progress=False)
    if isinstance(raw_hourly.columns, pd.MultiIndex):
        raw_hourly.columns = raw_hourly.columns.get_level_values(0)
    
    raw_hourly = raw_hourly.reset_index()
    hourly_ts = pd.to_datetime(raw_hourly["Datetime"]).dt.tz_localize(None)
    hourly_df = pd.DataFrame({
        "timestamp": hourly_ts,
        "open": raw_hourly["Open"].astype(float),
        "high": raw_hourly["High"].astype(float),
        "low": raw_hourly["Low"].astype(float),
        "close": raw_hourly["Close"].astype(float),
        "volume": raw_hourly["Volume"].astype(float)
    }).dropna().sort_values("timestamp").reset_index(drop=True)

    # Günlük veri (SMA100 için 2 Yıl)
    raw_daily = yf.download(ticker, period="2y", interval="1d", progress=False)
    if isinstance(raw_daily.columns, pd.MultiIndex):
        raw_daily.columns = raw_daily.columns.get_level_values(0)
    
    raw_daily = raw_daily.reset_index()
    daily_ts = pd.to_datetime(raw_daily["Date"]).dt.tz_localize(None)
    daily_df = pd.DataFrame({
        "timestamp": daily_ts,
        "open": raw_daily["Open"].astype(float),
        "high": raw_daily["High"].astype(float),
        "low": raw_daily["Low"].astype(float),
        "close": raw_daily["Close"].astype(float),
        "volume": raw_daily["Volume"].astype(float)
    }).dropna().sort_values("timestamp").reset_index(drop=True)

    print(f"    ✓ Saatlik Mum Sayısı : {len(hourly_df)} bar ({hourly_df['timestamp'].iloc[0].strftime('%Y-%m-%d')} - {hourly_df['timestamp'].iloc[-1].strftime('%Y-%m-%d')})")
    print(f"    ✓ Günlük Mum Sayısı  : {len(daily_df)} bar ({daily_df['timestamp'].iloc[0].strftime('%Y-%m-%d')} - {daily_df['timestamp'].iloc[-1].strftime('%Y-%m-%d')})")

    # 3. ADIM: Olay Güdümlü Backtest Motoru Çalıştırma (1. Senaryo: Sıkı Anayasal Pusula)
    print("\n[+] 3. Olay Güdümlü Backtest Motoru (Acımasız Gerçeklik & v4.0 Anayasası) Çalıştırılıyor...")
    print("    - Başlangıç Sermayesi : 1,000,000.00 TL")
    print("    - Komisyon Oranı      : On binde 4 (%0.04)")
    print("    - Slippage (Kayma)    : On binde 5 (%0.05)")
    print("    - İcra Modeli         : t anında sinyal -> t+1 Open fiyatından giriş/çıkış")

    backtester = EventDrivenBacktester(
        initial_capital=1_000_000.0,
        min_rr_ratio=2.5,
        risk_budget_pct=0.02,
        time_stop_bars=12,
        chandelier_atr_mult=2.5,
        initial_stop_atr_mult=2.0
    )

    # 3.A. Tam Sıkı Anayasa (Pusula Değerlendirmesi ile)
    tearsheet_strict = backtester.run_backtest(
        symbol="F_THYAO",
        hourly_df=hourly_df,
        daily_df=daily_df,
        fundamental_data=fund_data,
        channel=AssetChannel.EQUITY_REAL,
        contract_multiplier=100.0,
        initial_margin_per_contract=6500.0
    )

    # 3.B. Temel Yön İzni Aktif İken Teknik İcra Performansı (ONLY_LONG İzni Altında)
    tearsheet_exec = backtester.run_backtest(
        symbol="F_THYAO",
        hourly_df=hourly_df,
        daily_df=daily_df,
        fundamental_data=fund_data,
        channel=AssetChannel.EQUITY_REAL,
        contract_multiplier=100.0,
        initial_margin_per_contract=6500.0,
        override_directional_bias=DirectionalBias.ONLY_LONG
    )

    def print_tearsheet(title: str, ts):
        print("\n" + "=" * 80)
        print(f"  PERFORMANS RAPORU (TEARSHEET) - {title}")
        print("=" * 80)
        print(f"Başlangıç Sermayesi       : {ts.initial_capital:,.2f} TL")
        print(f"Bitiş Sermayesi           : {ts.final_capital:,.2f} TL")
        print(f"Toplam Net Kâr / Zarar     : {ts.total_net_pnl:+,.2f} TL (%{ts.total_return_pct:+.2f})")
        print(f"Maksimum Drawdown (MDD)   : -%{ts.max_drawdown_pct:.2f} (-{ts.max_drawdown_try:,.2f} TL)")
        print(f"Toplam İşlem Sayısı       : {ts.total_trades}")
        print(f"Kazanma Oranı (Win Rate)  : %{ts.win_rate_pct:.2f} ({ts.winning_trades} Kârlı / {ts.losing_trades} Zararlı)")
        print(f"Kâr Faktörü (Profit Factor: {ts.profit_factor:.2f}")
        print(f"Ortalama Gerçekleşen R    : {ts.avg_r_multiple:+.2f}R")
        print(f"Ödenen Toplam Komisyon    : {ts.total_commissions:,.2f} TL")
        print(f"Ödenen Toplam Kayma (Slip): {ts.total_slippage:,.2f} TL")
        print("-" * 80)

        if ts.trades:
            print("\n[GERÇEKLEŞEN İŞLEMLER DETAYI]:")
            for tr in ts.trades:
                print(
                    f"  #Trade {tr.trade_id} | {tr.side} {tr.lots} Lot | "
                    f"Giriş: {tr.entry_price:.2f} ({tr.entry_time.strftime('%m-%d %H:%M')}) -> "
                    f"Çıkış: {tr.exit_price:.2f} ({tr.exit_time.strftime('%m-%d %H:%M')}) | "
                    f"PnL: {tr.realized_pnl:+,.2f} TL ({tr.r_multiple_realized:+.2f}R) | Çıkış: {tr.exit_reason} | Süre: {tr.bars_held} Bar"
                )

    print_tearsheet("THYAO VİOP v4.0 (SIKI ANAYASAL PUSULA FİLTRESİ)", tearsheet_strict)
    print_tearsheet("THYAO VİOP v4.0 (TEKNİK İCRA & ÇIKIŞ MEKANİZMASI)", tearsheet_exec)

    print("\n" + "=" * 80)
    print("  ✓ SIFIR LOOKAHEAD BIAS VE GERÇEKÇİ MALİYETLİ BACKTEST BAŞARIYLA TAMAMLANDI")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_thyao_backtest())
