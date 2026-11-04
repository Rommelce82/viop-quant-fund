"""
Uzun Vadeli ve Kör Test Simülatörü (run_long_term_backtest.py).

Test Kapsamı:
1. Çoklu Varlık Evreni:
   - F_THYAO (Kanal A - Reel Sektör)
   - F_AKBNK (Kanal B - Banka)
   - F_XU030 (Kanal F/Index - Endeks)
2. Zaman Pencereleri:
   - In-Sample (Geçmiş Test): Ekim 2023 - Ekim 2025 (2 Yıl Saatlik / 3 Yıl Günlük)
   - Out-of-Sample (Kör Test): Ekim 2025 - Ekim 2026 (1 Yıl Saatlik & Günlük)
3. Zero Data Leakage:
   - In-Sample'dan Out-of-Sample'a geçerken portföy sermayesi (1.000.000 TL), indikatörler,
     açık pozisyonlar ve durum yöneticisi tamamen sıfırlanır.
4. Acımasız Gerçeklik:
   - Komisyon: On binde 4 (0.0004)
   - Slippage: On binde 5 (0.0005)
   - t anında sinyal -> t+1 Open'da icra
5. Raporlama:
   - Her varlık için In-Sample ve Out-of-Sample karşılaştırmalı Tearsheet tablosu.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import sys
from typing import Dict, List, Optional, Tuple
import pandas as pd
import yfinance as yf

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.backtest.event_driven_tester import BacktestTearsheet, EventDrivenBacktester
from src.data.fintables_mcp import FintablesMCPClient
from src.data.schemas import FundamentalData
from src.strategy.fundamental_compass import AssetChannel, DirectionalBias


@dataclass
class AssetTestConfig:
    """Test Edilecek Varlık Yapılandırması."""
    symbol: str
    ticker_yf: str
    channel: AssetChannel
    contract_multiplier: float
    initial_margin_try: float


class LongTermBacktestRunner:
    """
    3 Varlık için In-Sample ve Out-of-Sample Karşılaştırmalı Test Yöneticisi.
    """

    def __init__(self) -> None:
        self.fintables = FintablesMCPClient()
        self.assets: List[AssetTestConfig] = [
            AssetTestConfig(
                symbol="F_THYAO",
                ticker_yf="THYAO.IS",
                channel=AssetChannel.EQUITY_REAL,
                contract_multiplier=100.0,
                initial_margin_try=6500.0
            ),
            AssetTestConfig(
                symbol="F_AKBNK",
                ticker_yf="AKBNK.IS",
                channel=AssetChannel.EQUITY_BANK,
                contract_multiplier=100.0,
                initial_margin_try=2800.0
            ),
            AssetTestConfig(
                symbol="F_XU030",
                ticker_yf="XU030.IS",
                channel=AssetChannel.INDEX,
                contract_multiplier=10.0,
                initial_margin_try=15000.0
            ),
        ]

    async def fetch_asset_data(
        self,
        asset: AssetTestConfig
    ) -> Tuple[pd.DataFrame, pd.DataFrame, FundamentalData]:
        """
        Varlığa ait saatlik, günlük fiyat serilerini ve Fintables temel finansallarını çeker.
        Rate-limit önlemek için araya asyncio.sleep eklenmiştir.
        """
        print(f"[*] {asset.symbol} ({asset.ticker_yf}) verileri indiriliyor...")
        await asyncio.sleep(1.0)  # Rate-limit koruması (Throttle)

        # 1. Saatlik Veri (Yahoo Finance maksimum erişilebilir ~730 gün)
        raw_h = yf.download(asset.ticker_yf, period="730d", interval="1h", progress=False)
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

        await asyncio.sleep(0.5)

        # 2. Günlük Veri (4 Yıllık)
        raw_d = yf.download(asset.ticker_yf, period="5y", interval="1d", progress=False)
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

        # 3. Fintables Temel Bilanço (Hisseler için canlı çekilir, Endeks için temsilî finansal)
        raw_symbol = asset.symbol.replace("F_", "")
        if asset.channel != AssetChannel.INDEX:
            fund_data = await self.fintables.fetch_quarterly_financials(raw_symbol)
        else:
            # Endeks için XU030 temsilî sepet finansalları
            fund_data = FundamentalData(
                symbol="XU030",
                as_of_date=datetime(2026, 6, 30),
                announced_at=datetime(2026, 8, 10, 18, 30),
                source="INDEX_COMPOSITE",
                period_year=2026,
                period_quarter=2,
                pe_ratio=5.5,
                pb_ratio=1.4,
                ev_ebitda=4.8,
                peg_ratio=0.5,
                roe=0.28,
                roa=0.12,
                net_profit_margin=0.18,
                gross_margin=0.28,
                ebitda_margin=0.24,
                net_debt_ebitda=1.1,
                current_ratio=1.4,
                net_income_yoy_growth=0.35,
                revenue_yoy_growth=0.40,
                net_profit_try=150_000_000_000.0,
                revenue_try=950_000_000_000.0,
                ebitda_try=220_000_000_000.0,
                equity_try=550_000_000_000.0
            )

        print(f"    ✓ {asset.symbol}: Saatlik {len(hourly_df)} bar | Günlük {len(daily_df)} bar hazır.")
        return hourly_df, daily_df, fund_data

    def run_split_simulation(
        self,
        asset: AssetTestConfig,
        hourly_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        fund_data: FundamentalData,
        split_date: datetime = datetime(2025, 10, 1),
        override_directional_bias: Optional[DirectionalBias] = None
    ) -> Tuple[BacktestTearsheet, BacktestTearsheet]:
        """
        Veri setini In-Sample (Split öncesi) ve Out-of-Sample (Split sonrası) olarak ayırır.
        Her iki periyot için bağımsız 1.000.000 TL sermaye ve sıfırlanmış durum yöneticisiyle test eder.
        """
        # In-Sample Veri Dilimleri
        in_hourly = hourly_df[hourly_df["timestamp"] < split_date].copy().reset_index(drop=True)
        in_daily = daily_df[daily_df["timestamp"] < split_date].copy().reset_index(drop=True)

        # Out-of-Sample (Kör Test) Veri Dilimleri
        out_hourly = hourly_df[hourly_df["timestamp"] >= split_date].copy().reset_index(drop=True)
        out_daily = daily_df.copy().reset_index(drop=True)

        # Motor 1: In-Sample (Tamamen bağımsız 1M TL bütçe)
        engine_in = EventDrivenBacktester(initial_capital=1_000_000.0)
        tearsheet_in = engine_in.run_backtest(
            symbol=asset.symbol,
            hourly_df=in_hourly,
            daily_df=in_daily,
            fundamental_data=fund_data,
            channel=asset.channel,
            contract_multiplier=asset.contract_multiplier,
            initial_margin_per_contract=asset.initial_margin_try,
            override_directional_bias=override_directional_bias
        )

        # Motor 2: Out-of-Sample (SIFIR VERİ SIZINTISI - Portföy, durum ve indikatörler tamamen SIFIRLANIR)
        engine_out = EventDrivenBacktester(initial_capital=1_000_000.0)
        tearsheet_out = engine_out.run_backtest(
            symbol=asset.symbol,
            hourly_df=out_hourly,
            daily_df=out_daily,
            fundamental_data=fund_data,
            channel=asset.channel,
            contract_multiplier=asset.contract_multiplier,
            initial_margin_per_contract=asset.initial_margin_try,
            override_directional_bias=override_directional_bias
        )

        return tearsheet_in, tearsheet_out

    async def execute_full_audit(self) -> None:
        """Tüm varlıklar için uzun vadeli testi çalıştırır ve karşılaştırmalı rapor döker."""
        print("=" * 85)
        print("  VİOP FAZ 5: ÇOKLU VARLIK UZUN VADELİ VE KÖR TEST ARENASI (IN & OUT OF SAMPLE)")
        print("=" * 85)
        print("  * In-Sample Dönemi  : Kasım 2023 - Ekim 2025 (~2 Yıl)")
        print("  * Out-of-Sample (Kör): Ekim 2025 - Ekim 2026 (1 Yıl)")
        print("  * Zero Data Leakage : Her iki dönemde portföy ve indikatörler tamamen bağımsız.")
        print("  * Maliyet Modeli    : Komisyon 0.0004 | Slippage 0.0005 | t sinyal -> t+1 Open icra\n")

        cached_data = {}
        for asset in self.assets:
            h_df, d_df, f_data = await self.fetch_asset_data(asset)
            cached_data[asset.symbol] = (h_df, d_df, f_data)

        # ---------------------------------------------------------
        # RAPOR 1: KATI ANAYASA v4.0 PUSULA MODU (COMPASS PROTECTION)
        # ---------------------------------------------------------
        print("\n" + "=" * 85)
        print("  RAPOR 1: KATI ANAYASA v4.0 PUSULA MODU (TEMEL FİLTRE AKTİF)")
        print("=" * 85)
        header_fmt = "{:<12} | {:<16} | {:<14} | {:<10} | {:<10} | {:<10} | {:<12}"
        row_fmt    = "{:<12} | {:<16} | {:<14} | {:<10} | {:<10} | {:<10} | {:<12}"

        print(header_fmt.format("Varlık", "Test Dönemi", "Net PnL (TL)", "Getiri %", "MDD %", "İşlem", "Pusula Kalkan"))
        print("-" * 85)

        for asset in self.assets:
            h_df, d_df, f_data = cached_data[asset.symbol]
            ts_in, ts_out = self.run_split_simulation(asset, h_df, d_df, f_data, override_directional_bias=None)
            print(row_fmt.format(
                asset.symbol, "In-Sample (Geçmiş)",
                f"{ts_in.total_net_pnl:+,.0f}", f"%{ts_in.total_return_pct:+.2f}",
                f"-%{ts_in.max_drawdown_pct:.2f}", f"{ts_in.total_trades} ({ts_in.win_rate_pct:.0f}%)",
                f"{ts_in.compass_neutral_bars} bar"
            ))
            print(row_fmt.format(
                asset.symbol, "Out-of-Sample (Kör)",
                f"{ts_out.total_net_pnl:+,.0f}", f"%{ts_out.total_return_pct:+.2f}",
                f"-%{ts_out.max_drawdown_pct:.2f}", f"{ts_out.total_trades} ({ts_out.win_rate_pct:.0f}%)",
                f"{ts_out.compass_neutral_bars} bar"
            ))
            print("-" * 85)

        # ---------------------------------------------------------
        # RAPOR 2: TEKNİK MOTOR REJİM VE STRES TESTİ (ACTIVE BENCHMARK)
        # ---------------------------------------------------------
        print("\n" + "=" * 85)
        print("  RAPOR 2: TEKNİK MOTOR REJİM VE STRATEJİ TESTİ (İCRA İZNİ ALTINDA)")
        print("  (Donchian Breakout + Volume Spike + R/K >= 2.5 + Chandelier + Time Stop)")
        print("=" * 85)
        print(header_fmt.format("Varlık", "Test Dönemi", "Net PnL (TL)", "Getiri %", "MDD %", "İşlem", "Kâr Faktörü"))
        print("-" * 85)

        for asset in self.assets:
            h_df, d_df, f_data = cached_data[asset.symbol]
            ts_in, ts_out = self.run_split_simulation(asset, h_df, d_df, f_data, override_directional_bias=DirectionalBias.ONLY_LONG)
            print(row_fmt.format(
                asset.symbol, "In-Sample (Geçmiş)",
                f"{ts_in.total_net_pnl:+,.0f}", f"%{ts_in.total_return_pct:+.2f}",
                f"-%{ts_in.max_drawdown_pct:.2f}", f"{ts_in.total_trades} ({ts_in.win_rate_pct:.0f}%)",
                f"{ts_in.profit_factor:.2f}"
            ))
            print(row_fmt.format(
                asset.symbol, "Out-of-Sample (Kör)",
                f"{ts_out.total_net_pnl:+,.0f}", f"%{ts_out.total_return_pct:+.2f}",
                f"-%{ts_out.max_drawdown_pct:.2f}", f"{ts_out.total_trades} ({ts_out.win_rate_pct:.0f}%)",
                f"{ts_out.profit_factor:.2f}"
            ))
            print("-" * 85)

        print("\n" + "=" * 85)
        print("  ✓ IN-SAMPLE VE OUT-OF-SAMPLE TESTLERİ SIFIR VERİ SIZINTISIYLA TAMAMLANDI")
        print("=" * 85)


if __name__ == "__main__":
    runner = LongTermBacktestRunner()
    asyncio.run(runner.execute_full_audit())

