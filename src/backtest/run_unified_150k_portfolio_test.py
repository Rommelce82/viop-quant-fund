"""
🏛️ TEK KASA (150.000 TL) EŞZAMANLI ÇOKLU VARLIK VİOP PORTFÖY TESTİ (v4.2)
(src/backtest/run_unified_150k_portfolio_test.py)

ChatGPT Codex Denetim Düzeltmesi & Gerçekçi Portföy Simülasyonu:
- Başlangıç Sermayesi: TEK KASA 150.000 TL (Varlık başına izole değil, tüm portföy için ortak tek nakit havuzu).
- 20 VİOP Sözleşmesi Eşzamanlı (Simultaneous) ve Ortak Teminatlı (Shared Margin Pool) çalışır.
- İşleme girildikçe başlangıç teminatı (Initial Margin) 150.000 TL'lik ortak kasadan rezerve edilir.
- Boşta kalan tek serbest teminat (Free Margin) Akbank ALE Para Piyasası Fonu'nda (%48 brüt, %17.5 stopajlı net nema) günlük olarak nemalanır.
- Teminat yetersiz kaldığında yeni pozisyon açılamaz (Margin Rejection / Ali Perşembe Risk Kalkanı).
- %4.0 Gün İçi Devre Kesici (Circuit Breaker) tekil hisse üzerinden değil, KONSOLİDE PORTFÖY ÖZSERMAYESİ (MTM Total NAV) üzerinden tetiklenir.
- Midas Çift Taraflı Kademeli Komisyon Tarifesi kümülatif portföy işlem hacmiyle kademe atlar.
- Zaman Dilimi: 240 Dakikalık Seans Barları (14:15 Öğle & 18:15 Kapanış).
- In-Sample (Ekim 2023 - Ekim 2025: 2 Yıl) ve Out-of-Sample / Kör Test (Ekim 2025 - Ekim 2026: 1 Yıl).
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import yfinance as yf

# Proje kökünü sys.path'e ekle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.backtest.event_driven_tester import EventDrivenBacktester, TradeRecord
from src.data.schemas import FundamentalData
from src.strategy.fundamental_compass import (
    AssetChannel,
    CostOfCarryInput,
    DirectionalBias,
    FundamentalCompass,
    MarketMicrostructureInput
)
from src.strategy.position_manager import PositionState
from src.strategy.technical_executioner import (
    ExecutionActionV4,
    TechnicalDecisionV4,
    TechnicalExecutioner
)


@dataclass
class ContractMeta:
    symbol: str
    ticker_yf: str
    channel: AssetChannel
    category: str
    contract_multiplier: float
    initial_margin_try: float


class Unified150kPortfolioTester:
    """
    Tek Kasa (150.000 TL) Eşzamanlı Çoklu Varlık Portföy Backtest Motoru.
    """

    SLIPPAGE_RATE = 0.0002  # Limit at Best Ask/Bid ile On binde 2 kayma

    LONG_ENTRIES = (
        ExecutionActionV4.ENTER_LONG,
        ExecutionActionV4.ENTER_LONG_B_TYPE,
        ExecutionActionV4.ENTER_LONG_A_TYPE,
        ExecutionActionV4.ENTER_BREAKAWAY_GAP
    )
    SHORT_ENTRIES = (
        ExecutionActionV4.ENTER_SHORT,
        ExecutionActionV4.ENTER_SHORT_B_TYPE,
        ExecutionActionV4.ENTER_SHORT_A_TYPE
    )

    def __init__(self, initial_capital: float = 150_000.0) -> None:
        self.initial_capital = initial_capital
        self.compass = FundamentalCompass()
        self.executioner = TechnicalExecutioner(time_stop_bars=15)
        self.executioner.TIME_STOP_BARS = 15
        self.executioner.CHANDELIER_ATR_MULT = 2.5
        self.executioner.INITIAL_STOP_ATR_MULT = 2.0

    @staticmethod
    def get_midas_commission_rate(cumulative_volume_try: float) -> float:
        """Midas Kademeli Komisyon Tarifesi (Çift Taraflı)."""
        if cumulative_volume_try < 10_000_000.0:
            return 0.0005
        elif cumulative_volume_try < 100_000_000.0:
            return 0.0002
        else:
            return 0.0001

    def run_unified_simulation(
        self,
        contracts: List[ContractMeta],
        asset_hourly_dfs: Dict[str, pd.DataFrame],
        asset_daily_dfs: Dict[str, pd.DataFrame],
        asset_funds: Dict[str, FundamentalData],
        start_date: datetime,
        end_date: datetime,
        test_label: str = "IN_SAMPLE"
    ) -> Dict[str, Any]:
        """
        Tüm varlıkların 240m barlarını zaman damgası bazında kronolojik sıraya dizip
        ortak 150.000 TL havuz üzerinden simüle eder.
        """
        # 1. 240m barlara resample et ve global zaman çizelgesi çıkar
        asset_240m_dfs: Dict[str, pd.DataFrame] = {}
        all_timestamps = set()

        for c in contracts:
            sym = c.symbol
            h_df = asset_hourly_dfs.get(sym)
            if h_df is None or h_df.empty:
                continue
            # Tarih filtresi
            sub_h = h_df[(h_df["timestamp"] >= start_date) & (h_df["timestamp"] <= end_date)].copy()
            if sub_h.empty:
                continue
            df_240 = EventDrivenBacktester.resample_bars(sub_h, 240)
            df_240 = df_240.sort_values("timestamp").reset_index(drop=True)
            if len(df_240) >= 10:
                asset_240m_dfs[sym] = df_240
                all_timestamps.update(df_240["timestamp"].tolist())

        sorted_timestamps = sorted(list(all_timestamps))
        print(f"[*] [{test_label}] Senkronize Zaman Çizelgesi: {len(sorted_timestamps)} seans barı ({len(asset_240m_dfs)} aktif sözleşme).")

        # Portföy Durum Değişkenleri (TEK KASA)
        cash = self.initial_capital
        peak_nav = cash
        max_drawdown_try = 0.0
        max_drawdown_pct = 0.0

        positions: Dict[str, PositionState] = {}
        locked_margins: Dict[str, float] = {}
        pending_orders: Dict[str, Dict[str, Any]] = {}

        cumulative_volume_try = 0.0
        total_commissions_paid = 0.0
        total_slippage_paid = 0.0
        total_ale_net_income = 0.0
        total_ale_tax_paid = 0.0

        completed_trades: List[TradeRecord] = []
        trade_counter = 0
        pyramid_count = 0
        rejected_margin_count = 0

        current_calendar_day: Optional[date] = None
        day_start_nav = cash
        circuit_breaker_active = False

        nav_history: List[Dict[str, Any]] = []

        # Her varlık için bar indeksi takipçisi
        bar_pointers: Dict[str, int] = {sym: 0 for sym in asset_240m_dfs.keys()}

        for current_time in sorted_timestamps:
            bar_date = current_time.date() if hasattr(current_time, "date") else current_time

            # -------------------------------------------------------------
            # A. GÜN DEĞİŞİMİ: ALE FONU GÜNLÜK NEMASI & DEVRE KESİCİ SIFIRLAMA
            # -------------------------------------------------------------
            if current_calendar_day != bar_date:
                if current_calendar_day is not None:
                    # Önceki günün boşta kalan serbest nakdine ALE repo neması tahakkuk ettir
                    free_cash_for_ale = max(0.0, cash - sum(locked_margins.values()))
                    if free_cash_for_ale > 0:
                        daily_gross = free_cash_for_ale * (0.48 / 365.0)
                        daily_tax = daily_gross * 0.175
                        daily_net = daily_gross - daily_tax
                        cash += daily_net
                        total_ale_net_income += daily_net
                        total_ale_tax_paid += daily_tax

                current_calendar_day = bar_date
                # Gün başlangıç MTM NAV hesapla
                unrealized_sum = 0.0
                for sym, pos in positions.items():
                    if pos.is_active:
                        c_meta = next(x for x in contracts if x.symbol == sym)
                        # O anki fiyattan MTM değerleme
                        df_240 = asset_240m_dfs[sym]
                        ptr = bar_pointers[sym]
                        if ptr < len(df_240):
                            cur_p = float(df_240.iloc[ptr]["open"])
                            if pos.lots > 0:
                                unrealized_sum += (cur_p - pos.entry_price) * pos.lots * c_meta.contract_multiplier
                            else:
                                unrealized_sum += (pos.entry_price - cur_p) * abs(pos.lots) * c_meta.contract_multiplier

                day_start_nav = cash + unrealized_sum
                circuit_breaker_active = False

            # -------------------------------------------------------------
            # B. ÖNCEKİ BARDAN GELEN EMİRLERİN İCRASI (BAR OPEN İLE)
            # -------------------------------------------------------------
            for sym in list(pending_orders.keys()):
                order = pending_orders.pop(sym)
                c_meta = next(x for x in contracts if x.symbol == sym)
                df_240 = asset_240m_dfs[sym]
                ptr = bar_pointers[sym]
                if ptr >= len(df_240):
                    continue

                bar_now = df_240.iloc[ptr]
                cur_open = float(bar_now["open"])
                order_action = order["action"]
                lots_req = order["lots"]

                if order_action in self.LONG_ENTRIES or order_action in self.SHORT_ENTRIES:
                    # Devre kesici kontrolü
                    if circuit_breaker_active:
                        continue

                    # Ortak Kasa Teminat Kontrolü
                    req_margin = lots_req * c_meta.initial_margin_try
                    current_free_margin = cash - sum(locked_margins.values())

                    # Teminat yetersizse lot küçült veya reddet
                    if current_free_margin < req_margin:
                        affordable_lots = math.floor(current_free_margin / c_meta.initial_margin_try)
                        if affordable_lots >= 1:
                            lots_req = affordable_lots
                            req_margin = lots_req * c_meta.initial_margin_try
                        else:
                            rejected_margin_count += 1
                            continue  # Yetersiz teminat sebebiyle veto

                    # İcra Fiyatı & Kayma
                    is_long = (order_action in self.LONG_ENTRIES)
                    exec_slip = cur_open * self.SLIPPAGE_RATE
                    exec_price = cur_open + exec_slip if is_long else cur_open - exec_slip
                    total_slippage_paid += exec_slip * lots_req * c_meta.contract_multiplier

                    # Komisyon
                    notional = exec_price * lots_req * c_meta.contract_multiplier
                    comm_rate = self.get_midas_commission_rate(cumulative_volume_try)
                    entry_comm = notional * comm_rate
                    cumulative_volume_try += notional
                    total_commissions_paid += entry_comm
                    cash -= entry_comm

                    # Teminat Blokesi
                    locked_margins[sym] = req_margin

                    # Pozisyon Oluştur
                    signed_lots = lots_req if is_long else -lots_req
                    positions[sym] = PositionState(
                        symbol=sym,
                        entry_price=round(exec_price, 2),
                        initial_stop=round(order["stop_price"], 2),
                        trailing_stop=round(order["stop_price"], 2),
                        lots=signed_lots,
                        bars_held=0,
                        scaled_out=False,
                        entry_time=current_time,
                        r_unit_price=order["r_unit"],
                        entry_commission_paid=entry_comm
                    )

                elif order_action == ExecutionActionV4.PYRAMID_ADD_33:
                    if sym not in positions or not positions[sym].is_active:
                        continue
                    pos = positions[sym]
                    req_margin = lots_req * c_meta.initial_margin_try
                    current_free_margin = cash - sum(locked_margins.values())

                    if current_free_margin >= req_margin:
                        is_long = pos.lots > 0
                        exec_slip = cur_open * self.SLIPPAGE_RATE
                        exec_price = cur_open + exec_slip if is_long else cur_open - exec_slip
                        total_slippage_paid += exec_slip * lots_req * c_meta.contract_multiplier

                        notional = exec_price * lots_req * c_meta.contract_multiplier
                        comm_rate = self.get_midas_commission_rate(cumulative_volume_try)
                        entry_comm = notional * comm_rate
                        cumulative_volume_try += notional
                        total_commissions_paid += entry_comm
                        cash -= entry_comm

                        locked_margins[sym] += req_margin
                        pos.add_pyramid(lots_req)
                        pyramid_count += 1

                elif order_action == ExecutionActionV4.SCALE_OUT_33:
                    if sym not in positions or not positions[sym].is_active:
                        continue
                    pos = positions[sym]
                    is_long = pos.lots > 0
                    exec_slip = cur_open * self.SLIPPAGE_RATE
                    exec_price = cur_open - exec_slip if is_long else cur_open + exec_slip
                    total_slippage_paid += exec_slip * lots_req * c_meta.contract_multiplier

                    notional = exec_price * lots_req * c_meta.contract_multiplier
                    comm_rate = self.get_midas_commission_rate(cumulative_volume_try)
                    exit_comm = notional * comm_rate
                    cumulative_volume_try += notional
                    total_commissions_paid += exit_comm

                    if is_long:
                        gross_pnl = (exec_price - pos.entry_price) * lots_req * c_meta.contract_multiplier
                    else:
                        gross_pnl = (pos.entry_price - exec_price) * lots_req * c_meta.contract_multiplier
                    net_pnl = gross_pnl - exit_comm

                    # Teminat serbest bırakma ve nakit güncelleme
                    released_margin = lots_req * c_meta.initial_margin_try
                    locked_margins[sym] = max(0.0, locked_margins[sym] - released_margin)
                    cash += net_pnl

                    trade_counter += 1
                    r_realized = (net_pnl / (pos.r_unit_price * lots_req)) if pos.r_unit_price > 0 else 0.0
                    completed_trades.append(TradeRecord(
                        trade_id=trade_counter,
                        symbol=sym,
                        side="LONG" if is_long else "SHORT",
                        entry_time=pos.entry_time,
                        exit_time=current_time,
                        entry_price=pos.entry_price,
                        exit_price=round(exec_price, 2),
                        lots=lots_req,
                        initial_stop=pos.initial_stop,
                        r_unit=pos.r_unit_price,
                        realized_pnl=round(net_pnl, 2),
                        commission_paid=round(exit_comm, 2),
                        entry_commission=0.0,
                        exit_commission=round(exit_comm, 2),
                        slippage_paid=round(exec_slip * lots_req * c_meta.contract_multiplier, 2),
                        exit_reason="SCALE_OUT_33",
                        r_multiple_realized=round(r_realized, 2),
                        bars_held=pos.bars_held,
                        notional_value=round(notional, 2),
                        margin_used=round(released_margin, 2),
                        is_pyramid=True
                    ))

                    # Kalan lot güncelleme
                    if is_long:
                        pos.lots -= lots_req
                    else:
                        pos.lots += lots_req
                    pos.scaled_out = True

                elif order_action in (ExecutionActionV4.CHANDELIER_STOP_EXIT, ExecutionActionV4.TIME_STOP_EXIT, ExecutionActionV4.TREND_REVERSAL_EXIT, ExecutionActionV4.FRIDAY_CLOSE_EXIT, "END_OF_BACKTEST_CLOSEOUT"):
                    if sym not in positions or not positions[sym].is_active:
                        continue
                    pos = positions[sym]
                    is_long = pos.lots > 0
                    lots_to_close = abs(pos.lots)

                    exec_slip = cur_open * self.SLIPPAGE_RATE
                    exec_price = cur_open - exec_slip if is_long else cur_open + exec_slip
                    total_slippage_paid += exec_slip * lots_to_close * c_meta.contract_multiplier

                    notional = exec_price * lots_to_close * c_meta.contract_multiplier
                    comm_rate = self.get_midas_commission_rate(cumulative_volume_try)
                    exit_comm = notional * comm_rate
                    cumulative_volume_try += notional
                    total_commissions_paid += exit_comm

                    if is_long:
                        gross_pnl = (exec_price - pos.entry_price) * lots_to_close * c_meta.contract_multiplier
                    else:
                        gross_pnl = (pos.entry_price - exec_price) * lots_to_close * c_meta.contract_multiplier
                    net_pnl = gross_pnl - exit_comm

                    # Teminatı tamamen bırak ve nakde ekle
                    released_margin = locked_margins.pop(sym, 0.0)
                    cash += net_pnl

                    trade_counter += 1
                    r_realized = (net_pnl / (pos.r_unit_price * lots_to_close)) if pos.r_unit_price > 0 else 0.0
                    completed_trades.append(TradeRecord(
                        trade_id=trade_counter,
                        symbol=sym,
                        side="LONG" if is_long else "SHORT",
                        entry_time=pos.entry_time,
                        exit_time=current_time,
                        entry_price=pos.entry_price,
                        exit_price=round(exec_price, 2),
                        lots=lots_to_close,
                        initial_stop=pos.initial_stop,
                        r_unit=pos.r_unit_price,
                        realized_pnl=round(net_pnl, 2),
                        commission_paid=round(exit_comm, 2),
                        entry_commission=0.0,
                        exit_commission=round(exit_comm, 2),
                        slippage_paid=round(exec_slip * lots_to_close * c_meta.contract_multiplier, 2),
                        exit_reason=str(order_action),
                        r_multiple_realized=round(r_realized, 2),
                        bars_held=pos.bars_held,
                        notional_value=round(notional, 2),
                        margin_used=round(released_margin, 2),
                        is_pyramid=False
                    ))
                    pos.lots = 0
                    del positions[sym]

            # -------------------------------------------------------------
            # C. PORTFÖYÜN ANLIK KONSOLİDE MTM NAV VE DRAWDOWN HESABI
            # -------------------------------------------------------------
            unrealized_total = 0.0
            for sym, pos in positions.items():
                if pos.is_active:
                    c_meta = next(x for x in contracts if x.symbol == sym)
                    df_240 = asset_240m_dfs[sym]
                    ptr = bar_pointers[sym]
                    if ptr < len(df_240):
                        cur_p = float(df_240.iloc[ptr]["close"])
                        if pos.lots > 0:
                            unrealized_total += (cur_p - pos.entry_price) * pos.lots * c_meta.contract_multiplier
                        else:
                            unrealized_total += (pos.entry_price - cur_p) * abs(pos.lots) * c_meta.contract_multiplier

            current_portfolio_nav = cash + unrealized_total

            # Portföy Zirvesi ve Drawdown Takibi
            if current_portfolio_nav > peak_nav:
                peak_nav = current_portfolio_nav
            dd_try = peak_nav - current_portfolio_nav
            dd_pct = (dd_try / peak_nav) * 100.0 if peak_nav > 0 else 0.0
            if dd_try > max_drawdown_try:
                max_drawdown_try = dd_try
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

            # Gün İçi Devre Kesici Kontrolü (%4.0 Drawdown)
            if day_start_nav > 0:
                day_loss_pct = (current_portfolio_nav - day_start_nav) / day_start_nav
                if day_loss_pct <= -0.04:
                    circuit_breaker_active = True
                    # Yeni giriş emirlerini iptal et
                    for s in list(pending_orders.keys()):
                        if pending_orders[s]["action"] in self.LONG_ENTRIES or pending_orders[s]["action"] in self.SHORT_ENTRIES:
                            del pending_orders[s]

            nav_history.append({
                "timestamp": current_time,
                "nav": current_portfolio_nav,
                "cash": cash,
                "locked_margin": sum(locked_margins.values()),
                "unrealized_pnl": unrealized_total,
                "circuit_breaker": circuit_breaker_active
            })

            # -------------------------------------------------------------
            # D. SEANS SONU KARAR ÜRETİMİ (BAR CLOSE İLE)
            # -------------------------------------------------------------
            current_free_margin = max(0.0, cash - sum(locked_margins.values()))

            for sym, df_240 in asset_240m_dfs.items():
                ptr = bar_pointers[sym]
                if ptr >= len(df_240):
                    continue
                if df_240.iloc[ptr]["timestamp"] != current_time:
                    continue  # Bu bar bu varlıkta yok

                c_meta = next(x for x in contracts if x.symbol == sym)
                bar_row = df_240.iloc[ptr]
                pos_state = positions.get(sym)

                # Lookahead Bias önleme: Günlük veriler kesinlikle dünden önceki barlar olmalı
                daily_full = asset_daily_dfs.get(sym)
                if daily_full is None or daily_full.empty:
                    bar_pointers[sym] += 1
                    continue
                prior_daily = daily_full[daily_full["timestamp"].dt.date < bar_date].copy().reset_index(drop=True)
                if len(prior_daily) < 20:
                    bar_pointers[sym] += 1
                    continue

                past_hourly = df_240.iloc[:ptr + 1].copy().reset_index(drop=True)
                if len(past_hourly) < 20:
                    bar_pointers[sym] += 1
                    continue

                f_data = asset_funds.get(sym)
                if pos_state is not None and pos_state.is_active:
                    pos_state.bars_held += 1

                # Temel Pusula ve Yön İzni
                if pos_state is not None and pos_state.is_active:
                    bias = DirectionalBias.ONLY_LONG if pos_state.lots > 0 else DirectionalBias.ONLY_SHORT
                    compass_multiplier = 1.0
                else:
                    is_index = (c_meta.channel == AssetChannel.INDEX) or ("XU" in sym) or ("XBANK" in sym)
                    is_fx = (c_meta.channel == AssetChannel.FX)
                    is_comm = (c_meta.channel == AssetChannel.COMMODITY)
                    hourly_vol_try = float(bar_row["close"]) * float(bar_row["volume"])
                    default_adv = 1_500_000_000.0 if is_index else (500_000_000.0 if is_fx else (200_000_000.0 if is_comm else 80_000_000.0))
                    default_oi = 250_000 if is_index else (80_000 if is_fx else (50_000 if is_comm else 25_000))
                    micro = MarketMicrostructureInput(adv_try=max(default_adv, hourly_vol_try * 8.0), open_interest_contracts=default_oi)
                    carry = CostOfCarryInput(implied_irr=0.48, tcmb_funding_rate=0.50)
                    c_verdict, _ = self.compass.get_compass_verdict(
                        channel=c_meta.channel,
                        micro=micro,
                        carry=carry,
                        fundamental_data=f_data,
                        tcmb_policy_rate=0.50
                    )
                    dir_str = c_verdict.get("direction", "NEUTRAL") if isinstance(c_verdict, dict) else str(c_verdict)
                    bias = DirectionalBias(dir_str) if dir_str in DirectionalBias.__members__ else DirectionalBias.NEUTRAL
                    compass_multiplier = float(c_verdict.get("multiplier", 1.0)) if isinstance(c_verdict, dict) else 1.0

                # Karar Motorunu Çağır
                decision: TechnicalDecisionV4 = self.executioner.evaluate(
                    symbol=sym,
                    compass_bias=bias,
                    daily_data=prior_daily,
                    hourly_data=past_hourly,
                    position_state=pos_state,
                    portfolio_nav=current_portfolio_nav,
                    free_margin=current_free_margin,
                    compass_multiplier=compass_multiplier,
                    current_time_override=current_time
                )

                # Kararları sıraya al
                if decision.action in (
                    ExecutionActionV4.CHANDELIER_STOP_EXIT,
                    ExecutionActionV4.TIME_STOP_EXIT,
                    ExecutionActionV4.TREND_REVERSAL_EXIT,
                    ExecutionActionV4.FRIDAY_CLOSE_EXIT,
                    ExecutionActionV4.SCALE_OUT_33,
                    ExecutionActionV4.PYRAMID_ADD_33
                ):
                    pending_orders[sym] = {
                        "action": decision.action,
                        "lots": decision.target_lots,
                        "stop_price": decision.stop_price,
                        "r_unit": pos_state.r_unit_price if pos_state else 0.0
                    }
                elif decision.action in self.LONG_ENTRIES or decision.action in self.SHORT_ENTRIES:
                    if not circuit_breaker_active:
                        pending_orders[sym] = {
                            "action": decision.action,
                            "lots": decision.target_lots,
                            "stop_price": decision.stop_price,
                            "r_unit": abs(decision.entry_price - decision.stop_price) * c_meta.contract_multiplier
                        }

                bar_pointers[sym] += 1

        # -----------------------------------------------------------------
        # E. TEST SONU KALAN AÇIK POZİSYONLARI PİYASA FİYATINDAN LİKİDE ET
        # -----------------------------------------------------------------
        for sym in list(positions.keys()):
            pos = positions[sym]
            if not pos.is_active:
                continue
            c_meta = next(x for x in contracts if x.symbol == sym)
            df_240 = asset_240m_dfs[sym]
            last_close = float(df_240.iloc[-1]["close"])
            is_long = pos.lots > 0
            lots_to_close = abs(pos.lots)

            exec_slip = last_close * self.SLIPPAGE_RATE
            exec_price = last_close - exec_slip if is_long else last_close + exec_slip
            notional = exec_price * lots_to_close * c_meta.contract_multiplier
            comm_rate = self.get_midas_commission_rate(cumulative_volume_try)
            exit_comm = notional * comm_rate
            cumulative_volume_try += notional
            total_commissions_paid += exit_comm

            if is_long:
                gross_pnl = (exec_price - pos.entry_price) * lots_to_close * c_meta.contract_multiplier
            else:
                gross_pnl = (pos.entry_price - exec_price) * lots_to_close * c_meta.contract_multiplier
            net_pnl = gross_pnl - exit_comm

            released_margin = locked_margins.pop(sym, 0.0)
            cash += net_pnl

            trade_counter += 1
            completed_trades.append(TradeRecord(
                trade_id=trade_counter,
                symbol=sym,
                side="LONG" if is_long else "SHORT",
                entry_time=pos.entry_time,
                exit_time=sorted_timestamps[-1],
                entry_price=pos.entry_price,
                exit_price=round(exec_price, 2),
                lots=lots_to_close,
                initial_stop=pos.initial_stop,
                r_unit=pos.r_unit_price,
                realized_pnl=round(net_pnl, 2),
                commission_paid=round(exit_comm, 2),
                entry_commission=0.0,
                exit_commission=round(exit_comm, 2),
                slippage_paid=round(exec_slip * lots_to_close * c_meta.contract_multiplier, 2),
                exit_reason="END_OF_BACKTEST_CLOSEOUT",
                r_multiple_realized=0.0,
                bars_held=pos.bars_held,
                notional_value=round(notional, 2),
                margin_used=round(released_margin, 2),
                is_pyramid=False
            ))
            pos.lots = 0

        # Metriklerin Toplanması
        total_trade_pnl = sum(tr.realized_pnl for tr in completed_trades)
        final_nav = cash
        total_return_pct = ((final_nav - self.initial_capital) / self.initial_capital) * 100.0
        winning_trades = [tr for tr in completed_trades if tr.realized_pnl > 0]
        losing_trades = [tr for tr in completed_trades if tr.realized_pnl < 0]
        win_rate = (len(winning_trades) / len(completed_trades) * 100.0) if completed_trades else 0.0

        gross_profit = sum(tr.realized_pnl for tr in winning_trades)
        gross_loss = abs(sum(tr.realized_pnl for tr in losing_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        # Sözleşme bazında detay kırılımı
        contract_perf = {}
        for c in contracts:
            c_trades = [tr for tr in completed_trades if tr.symbol == c.symbol]
            c_pnl = sum(tr.realized_pnl for tr in c_trades)
            c_wins = [tr for tr in c_trades if tr.realized_pnl > 0]
            contract_perf[c.symbol] = {
                "trades": len(c_trades),
                "net_pnl": round(c_pnl, 2),
                "wins": len(c_wins),
                "win_rate": round(len(c_wins) / len(c_trades) * 100, 1) if c_trades else 0.0
            }

        return {
            "initial_capital": self.initial_capital,
            "final_nav": round(final_nav, 2),
            "trade_net_pnl": round(total_trade_pnl, 2),
            "ale_net_income": round(total_ale_net_income, 2),
            "ale_tax_paid": round(total_ale_tax_paid, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": len(completed_trades),
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_try": round(max_drawdown_try, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "total_commissions": round(total_commissions_paid, 2),
            "total_slippage": round(total_slippage_paid, 2),
            "pyramid_count": pyramid_count,
            "rejected_margin_count": rejected_margin_count,
            "contract_breakdown": contract_perf,
            "trades": [
                {
                    "id": tr.trade_id, "symbol": tr.symbol, "side": tr.side,
                    "pnl": tr.realized_pnl, "entry": tr.entry_price, "exit": tr.exit_price,
                    "lots": tr.lots, "comm": tr.commission_paid, "reason": tr.exit_reason,
                    "is_pyramid": tr.is_pyramid
                }
                for tr in completed_trades
            ]
        }


async def main():
    print("=" * 100)
    print("  VİOP v4.2 - TEK KASA (150.000 TL) EŞZAMANLI ÇOKLU VARLIK PORTFÖY TESTİ")
    print("  (Shared Margin Pool, Simultaneous 240m Bars, Single ALE Repo Pool, Global Circuit Breaker)")
    print("=" * 100)

    contracts = [
        ContractMeta("F_THYAO", "THYAO.IS", AssetChannel.EQUITY_REAL, "Hisse", 100.0, 6500.0),
        ContractMeta("F_AKBNK", "AKBNK.IS", AssetChannel.EQUITY_BANK, "Hisse", 100.0, 2200.0),
        ContractMeta("F_GARAN", "GARAN.IS", AssetChannel.EQUITY_BANK, "Hisse", 100.0, 3800.0),
        ContractMeta("F_EREGL", "EREGL.IS", AssetChannel.EQUITY_REAL, "Hisse", 100.0, 1800.0),
        ContractMeta("F_TUPRS", "TUPRS.IS", AssetChannel.EQUITY_REAL, "Hisse", 100.0, 4500.0),
        ContractMeta("F_XU030", "XU030.IS", AssetChannel.INDEX, "Endeks", 10.0, 18000.0),
        ContractMeta("F_XU100", "XU100.IS", AssetChannel.INDEX, "Endeks", 10.0, 12000.0),
        ContractMeta("F_XLBNK", "XBANK.IS", AssetChannel.INDEX, "Endeks", 10.0, 8000.0),
        ContractMeta("F_XUSIN", "XUSIN.IS", AssetChannel.INDEX, "Endeks", 10.0, 7500.0),
        ContractMeta("F_XGMYO", "XGMYO.IS", AssetChannel.INDEX, "Endeks", 10.0, 6000.0),
        ContractMeta("F_XAUUSD", "GC=F", AssetChannel.COMMODITY, "Emtia", 1.0, 3200.0),
        ContractMeta("F_XAGUSD", "SI=F", AssetChannel.COMMODITY, "Emtia", 10.0, 1500.0),
        ContractMeta("F_BRENT", "BZ=F", AssetChannel.COMMODITY, "Emtia", 10.0, 2500.0),
        ContractMeta("F_PLAT", "PL=F", AssetChannel.COMMODITY, "Emtia", 1.0, 2200.0),
        ContractMeta("F_COPPER", "HG=F", AssetChannel.COMMODITY, "Emtia", 100.0, 4000.0),
        ContractMeta("F_USDTRY", "USDTRY=X", AssetChannel.FX, "Döviz", 1000.0, 4000.0),
        ContractMeta("F_EURTRY", "EURTRY=X", AssetChannel.FX, "Döviz", 1000.0, 4500.0),
        ContractMeta("F_EURUSD", "EURUSD=X", AssetChannel.FX, "Döviz", 1000.0, 3000.0),
        ContractMeta("F_GBPTRY", "GBPTRY=X", AssetChannel.FX, "Döviz", 1000.0, 5000.0),
        ContractMeta("F_DXY", "DX-Y.NYB", AssetChannel.FX, "Döviz", 100.0, 3500.0),
    ]

    # Verileri İndir
    asset_hourly = {}
    asset_daily = {}
    asset_funds = {}

    fund_default = FundamentalData(
        symbol="VIOP",
        as_of_date=datetime(2025, 9, 30),
        announced_at=datetime(2025, 11, 5, 18, 0),
        source="HISTORICAL_AUDITED",
        period_year=2025,
        period_quarter=3,
        pe_ratio=6.0,
        pb_ratio=1.2,
        ev_ebitda=4.8,
        roe=0.30,
        roa=0.09,
        net_profit_margin=0.19,
        net_profit_try=30_000_000_000.0,
        revenue_try=140_000_000_000.0,
        ebitda_try=35_000_000_000.0,
        equity_try=150_000_000_000.0
    )

    for c in contracts:
        ticker = c.ticker_yf
        sym = c.symbol
        asset_funds[sym] = fund_default
        try:
            raw_h = yf.download(ticker, period="730d", interval="1h", progress=False)
            if isinstance(raw_h.columns, pd.MultiIndex):
                raw_h.columns = raw_h.columns.get_level_values(0)
            raw_h = raw_h.reset_index()
            t_col_h = "Datetime" if "Datetime" in raw_h.columns else "Date"
            hourly_ts = pd.to_datetime(raw_h[t_col_h]).dt.tz_localize(None)

            df_h = pd.DataFrame({
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

            df_d = pd.DataFrame({
                "timestamp": daily_ts,
                "open": raw_d["Open"].astype(float),
                "high": raw_d["High"].astype(float),
                "low": raw_d["Low"].astype(float),
                "close": raw_d["Close"].astype(float),
                "volume": raw_d["Volume"].astype(float) if "Volume" in raw_d.columns else 0.0
            }).dropna().sort_values("timestamp").reset_index(drop=True)

            if not df_h.empty and not df_d.empty:
                asset_hourly[sym] = df_h
                asset_daily[sym] = df_d
                print(f"  [+] {sym:<10} yüklendi ({len(df_h)} saatlik, {len(df_d)} günlük bar)")
        except Exception as e:
            print(f"  [!] {sym} indirilemedi: {e}")

    tester = Unified150kPortfolioTester(initial_capital=150_000.0)

    # 1. In-Sample Simülasyonu (Ekim 2023 - Ekim 2025)
    print("\n" + "=" * 80)
    print(">>> 1. IN-SAMPLE DÖNEMİ ÇALIŞTIRILIYOR (Ekim 2023 - Ekim 2025: 2 Yıl)...")
    print("=" * 80)
    in_results = tester.run_unified_simulation(
        contracts=contracts,
        asset_hourly_dfs=asset_hourly,
        asset_daily_dfs=asset_daily,
        asset_funds=asset_funds,
        start_date=datetime(2023, 10, 1),
        end_date=datetime(2025, 9, 30),
        test_label="IN_SAMPLE (2 YIL)"
    )

    # 2. Out-of-Sample / Kör Test Simülasyonu (Ekim 2025 - Ekim 2026)
    print("\n" + "=" * 80)
    print(">>> 2. OUT-OF-SAMPLE (KÖR TEST) DÖNEMİ ÇALIŞTIRILIYOR (Ekim 2025 - Ekim 2026: 1 Yıl)...")
    print("=" * 80)
    out_results = tester.run_unified_simulation(
        contracts=contracts,
        asset_hourly_dfs=asset_hourly,
        asset_daily_dfs=asset_daily,
        asset_funds=asset_funds,
        start_date=datetime(2025, 10, 1),
        end_date=datetime(2026, 10, 26),
        test_label="OUT_OF_SAMPLE (1 YIL KÖR TEST)"
    )

    # Kaydet
    output_data = {
        "metadata": {
            "title": "VİOP v4.2 - Tek Kasa (150.000 TL) Eşzamanlı Çoklu Varlık Portföy Testi",
            "initial_capital_try": 150_000.0,
            "generated_at": datetime.now().isoformat(),
            "execution_mode": "Unified Shared Margin Pool (Tek Kasa Ortak Teminat)",
            "timeframe": "240m Session Bars (14:15 & 18:15)",
            "commission_model": "Midas Çift Taraflı Kademeli",
            "ale_fund_model": "Akbank ALE Fonu %48 Brüt Repo / %17.5 Stopaj"
        },
        "in_sample": in_results,
        "out_of_sample": out_results
    }

    out_file = os.path.join(os.path.dirname(__file__), "..", "database", "unified_150k_portfolio_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n[OK] Tek kasa portföy sonuçları kaydedildi: {out_file}")

    print("\n" + "=" * 80)
    print("  ÖZET KARŞILAŞTIRMA (TEK 150.000 TL KASA)")
    print("=" * 80)
    print(f"Başlangıç Sermayesi       : {150_000:,.2f} TL")
    print(f"In-Sample Final NAV       : {in_results['final_nav']:,.2f} TL (Getiri: %{in_results['total_return_pct']:.1f})")
    print(f"In-Sample Trade Net PnL   : {in_results['trade_net_pnl']:,.2f} TL (İşlem: {in_results['total_trades']}, WR: %{in_results['win_rate_pct']:.1f})")
    print(f"In-Sample ALE Fon Neması  : {in_results['ale_net_income']:,.2f} TL")
    print(f"In-Sample Max Drawdown    : %{in_results['max_drawdown_pct']:.2f} ({in_results['max_drawdown_try']:,.2f} TL)")
    print("-" * 80)
    print(f"Kör Test Final NAV (OOS)  : {out_results['final_nav']:,.2f} TL (Getiri: %{out_results['total_return_pct']:.1f})")
    print(f"Kör Test Trade Net PnL    : {out_results['trade_net_pnl']:,.2f} TL (İşlem: {out_results['total_trades']}, WR: %{out_results['win_rate_pct']:.1f})")
    print(f"Kör Test ALE Fon Neması   : {out_results['ale_net_income']:,.2f} TL")
    print(f"Kör Test Max Drawdown     : %{out_results['max_drawdown_pct']:.2f} ({out_results['max_drawdown_try']:,.2f} TL)")
    print(f"Kör Test Kâr Faktörü (PF) : {out_results['profit_factor']:.2f}")
    print(f"Kör Test Piramitleme      : {out_results['pyramid_count']} adet")
    print(f"Yetersiz Teminat Reddi    : {out_results['rejected_margin_count']} adet")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
