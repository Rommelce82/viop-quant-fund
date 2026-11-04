"""
Olay Güdümlü VİOP Backtest ve Risk Doğrulama Motoru (v4.2).
(src/backtest/event_driven_tester.py)

Gereksinimler & Yenilikler:
1. Midas Çift Taraflı Kademeli Komisyon Tarifesi:
   - Hem Alım (Entry) hem Satım (Exit) bacaklarında uygulanır.
   - 0-10M: %0.05 (On binde 5), 10-100M: %0.02 (On binde 2), 100M+: %0.01 (On binde 1).
   - Kümülatif işlem hacmi hem alış hem satış notional değerleriyle büyür.
2. 240 Dakikalık Seans Pencereli Barlar:
   - 14:15 (Öğle Barı: 09:30-14:15) ve 18:15 (Seans Sonu Kapanış Barı: 14:15-18:15).
3. Limit Order at Best Ask/Bid & Kayma Yönetimi:
   - Kayma (Slippage) pasif limit emir standardında (On binde 2 / 0.0002).
4. Bedava Piramitleme (Free Pyramiding):
   - +2.0R kârda, risk sıfırken yeni 240m kırılımında %33 ek lot.
5. Devre Kesici (Circuit Breaker):
   - Gün içi %4.0 kasa erimesinde yeni işlem alımı dondurulur.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
import math
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from src.core.config import SystemConfig
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
class TradeRecord:
    """Tekil Gerçekleşen İşlem Kaydı."""
    trade_id: int
    symbol: str
    side: str                      # 'LONG' veya 'SHORT'
    entry_time: datetime
    exit_time: datetime
    entry_price: float             # Kayma dahil
    exit_price: float              # Kayma dahil
    lots: int
    initial_stop: float
    r_unit: float
    realized_pnl: float            # Komisyon ve kayma düşülmüş net TL
    commission_paid: float         # Çift taraflı toplam komisyon (Alış + Satış)
    entry_commission: float        # Alış bacağı komisyonu
    exit_commission: float         # Satış bacağı komisyonu
    slippage_paid: float
    exit_reason: str
    r_multiple_realized: float
    bars_held: int
    notional_value: float = 0.0    # Pozisyon Tutarı (TL)
    leverage: float = 0.0          # Efektif Kaldıraç Oranı
    margin_used: float = 0.0       # Bağlanan Teminat (TL)
    is_pyramid: bool = False       # Bedava piramitleme işlemi mi?


@dataclass
class BacktestTearsheet:
    """Backtest Performans Raporu (Tearsheet)."""
    initial_capital: float
    final_capital: float
    total_net_pnl: float
    total_return_pct: float
    max_drawdown_pct: float
    max_drawdown_try: float
    win_rate_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    profit_factor: float
    avg_r_multiple: float
    total_commissions: float       # Çift taraflı ödenen toplam komisyon
    total_slippage: float
    compass_neutral_bars: int = 0
    trades: List[TradeRecord] = field(default_factory=list)


class EventDrivenBacktester:
    """
    VİOP v4.2 Olay Güdümlü Backtest Motoru.
    """

    DEFAULT_COMMISSION_RATE = 0.0004   # Sabit taban
    SLIPPAGE_RATE = 0.0002             # Limit Order at Best Ask/Bid ile On binde 2 kayma

    @staticmethod
    def get_midas_commission_rate(cumulative_volume_try: float) -> float:
        """
        Midas VİOP Kademeli Komisyon Tarifesi (Çift Taraflı):
        - 0 – 10 Milyon TL   : On binde 5 (%0,05 / 0.0005)
        - 10 – 100 Milyon TL : On binde 2 (%0,02 / 0.0002)
        - 100 Milyon TL+     : On binde 1 (%0,01 / 0.0001)
        """
        if cumulative_volume_try < 10_000_000.0:
            return 0.0005
        elif cumulative_volume_try < 100_000_000.0:
            return 0.0002
        else:
            return 0.0001

    @staticmethod
    def resample_bars(df: pd.DataFrame, timeframe_minutes: int) -> pd.DataFrame:
        """
        Saatlik (veya 15m) barları 120m veya seans pencereli 240m barlara dönüştürür.
        240m için seans içi karar pencereleri:
        - 14:15 (Öğle Barı: 09:30 - 14:15)
        - 18:15 (Seans Sonu Kapanış Barı: 14:15 - 18:15)
        """
        if df.empty or timeframe_minutes <= 60:
            return df.copy()

        df_copy = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df_copy["timestamp"]):
            df_copy["timestamp"] = pd.to_datetime(df_copy["timestamp"])

        if timeframe_minutes == 240:
            # Borsa İstanbul seans pencereleri: 14:15 ve 18:15
            records = []
            df_copy["date"] = df_copy["timestamp"].dt.date
            for d, group in df_copy.groupby("date", sort=True):
                # Öğle Barı: saat <= 14 (veya 14:15)
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
                # Kapanış Barı: saat > 14 (15:00 - 18:15)
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

        # Standart resample (120m vb.)
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

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        config: Optional[SystemConfig] = None,
        use_midas_commission: bool = True,
        **kwargs: Any
    ) -> None:
        self.initial_capital = initial_capital
        self.config = config or SystemConfig()
        self.use_midas_commission = use_midas_commission
        
        # Parametreler
        self.min_rr_ratio = kwargs.get("min_rr_ratio", 2.0)
        self.risk_budget_pct = kwargs.get("risk_budget_pct", 0.02)
        self.time_stop_bars = kwargs.get("time_stop_bars", 30)
        self.chandelier_atr_mult = kwargs.get("chandelier_atr_mult", 2.5)
        self.initial_stop_atr_mult = kwargs.get("initial_stop_atr_mult", 2.0)
        self.volume_spike_mult = kwargs.get("volume_spike_mult", 1.4)

        # Modülleri yapılandır
        self.compass = FundamentalCompass()
        self.executioner = TechnicalExecutioner(config=self.config)
        
        self.executioner.MIN_RR_RATIO = self.min_rr_ratio
        self.executioner.RISK_BUDGET_PCT = self.risk_budget_pct
        self.executioner.TIME_STOP_BARS = self.time_stop_bars
        self.executioner.CHANDELIER_ATR_MULT = self.chandelier_atr_mult
        self.executioner.INITIAL_STOP_ATR_MULT = self.initial_stop_atr_mult

    def run_backtest(
        self,
        symbol: str,
        hourly_df: pd.DataFrame,
        daily_df: pd.DataFrame,
        fundamental_data: FundamentalData,
        channel: AssetChannel = AssetChannel.EQUITY_REAL,
        contract_multiplier: float = 100.0,
        initial_margin_per_contract: float = 6500.0,
        override_directional_bias: Optional[DirectionalBias] = None,
        timeframe_minutes: int = 60
    ) -> BacktestTearsheet:
        """
        Geçmiş veri üzerinde 240m veya 120m olay güdümlü simülasyonu çalıştırır.
        """
        if timeframe_minutes > 60:
            active_df = self.resample_bars(hourly_df, timeframe_minutes)
        else:
            active_df = hourly_df.copy()

        active_df = active_df.sort_values("timestamp").reset_index(drop=True)
        daily_df = daily_df.sort_values("timestamp").reset_index(drop=True)

        capital = self.initial_capital
        peak_capital = capital
        max_drawdown_try = 0.0
        max_drawdown_pct = 0.0
        compass_neutral_bars = 0

        # Midas Çift Taraflı Komisyon ve Hacim Takipçisi
        cumulative_traded_volume_try = 0.0
        total_commissions_paid = 0.0
        total_slippage_paid = 0.0

        # Gün içi devre kesici takibi (%4.0 Daily Drawdown)
        current_day_date: Optional[date] = None
        day_start_capital = capital
        circuit_breaker_active = False

        active_position: Optional[PositionState] = None
        pending_order: Optional[Dict[str, Any]] = None

        completed_trades: List[TradeRecord] = []
        trade_counter = 0

        # Başlangıç penceresi
        start_idx = min(50, max(20, len(active_df) // 4))
        total_bars = len(active_df)

        for t in range(start_idx, total_bars):
            current_bar = active_df.iloc[t]
            current_time = current_bar["timestamp"]
            current_open = float(current_bar["open"])
            current_high = float(current_bar["high"])
            current_low = float(current_bar["low"])
            current_close = float(current_bar["close"])

            # Gün değişimi ve Devre Kesici Kontrolü (Mark-to-Market NAV üzerinden)
            unrealized_pnl_open = 0.0
            if active_position is not None and active_position.is_active:
                if active_position.lots > 0:
                    unrealized_pnl_open = (current_open - active_position.entry_price) * active_position.lots * contract_multiplier
                else:
                    unrealized_pnl_open = (active_position.entry_price - current_open) * abs(active_position.lots) * contract_multiplier
            current_nav_open = capital + unrealized_pnl_open

            bar_date = current_time.date() if hasattr(current_time, "date") else current_time
            if current_day_date != bar_date:
                current_day_date = bar_date
                day_start_capital = current_nav_open
                circuit_breaker_active = False

            if day_start_capital > 0:
                day_dd_pct = (current_nav_open - day_start_capital) / day_start_capital
                if day_dd_pct <= -0.04:
                    circuit_breaker_active = True
                    pending_order = None  # Günlük erime %4'ü aştığında yeni emirler dondurulur

            # -----------------------------------------------------------------
            # 1. ADIM: BEKLEYEN EMRİN İCRASI (t+1 Open Fiyatından - Limit Order at Best)
            # -----------------------------------------------------------------
            if pending_order is not None and not circuit_breaker_active:
                order_side = pending_order["side"]
                target_lots = pending_order["lots"]
                is_pyramid_order = pending_order.get("is_pyramid", False)

                if order_side == "LONG":
                    fill_price = round(current_open * (1.0 + self.SLIPPAGE_RATE), 2)
                    slippage_cost = abs(fill_price - current_open) * target_lots * contract_multiplier
                    notional_val = fill_price * target_lots * contract_multiplier
                    
                    # Çift taraflı komisyon: Alış Bacağı
                    comm_rate = self.get_midas_commission_rate(cumulative_traded_volume_try) if self.use_midas_commission else self.DEFAULT_COMMISSION_RATE
                    entry_comm = notional_val * comm_rate
                    cumulative_traded_volume_try += notional_val
                    total_commissions_paid += entry_comm
                    total_slippage_paid += slippage_cost
                    capital -= entry_comm

                    if active_position is None:
                        active_position = PositionState(
                            symbol=symbol,
                            entry_price=fill_price,
                            initial_stop=pending_order["stop_price"],
                            trailing_stop=pending_order["stop_price"],
                            lots=target_lots,
                            entry_time=current_time,
                            r_unit_price=abs(fill_price - pending_order["stop_price"]),
                            entry_commission_paid=entry_comm
                        )
                    else:
                        # Bedava Piramitleme (Free Pyramiding - Tekilleştirilmiş lot ekleme)
                        active_position.add_pyramid(target_lots)
                        active_position.entry_commission_paid += entry_comm

                elif order_side == "SHORT":
                    fill_price = round(current_open * (1.0 - self.SLIPPAGE_RATE), 2)
                    slippage_cost = abs(current_open - fill_price) * target_lots * contract_multiplier
                    notional_val = fill_price * target_lots * contract_multiplier

                    # Çift taraflı komisyon: Alış Bacağı (Short Giriş)
                    comm_rate = self.get_midas_commission_rate(cumulative_traded_volume_try) if self.use_midas_commission else self.DEFAULT_COMMISSION_RATE
                    entry_comm = notional_val * comm_rate
                    cumulative_traded_volume_try += notional_val
                    total_commissions_paid += entry_comm
                    total_slippage_paid += slippage_cost
                    capital -= entry_comm

                    if active_position is None:
                        active_position = PositionState(
                            symbol=symbol,
                            entry_price=fill_price,
                            initial_stop=pending_order["stop_price"],
                            trailing_stop=pending_order["stop_price"],
                            lots=-target_lots,
                            entry_time=current_time,
                            r_unit_price=abs(pending_order["stop_price"] - fill_price),
                            entry_commission_paid=entry_comm
                        )
                    else:
                        # Bedava Piramitleme (Free Pyramiding Short - Tekilleştirilmiş lot ekleme)
                        active_position.add_pyramid(target_lots)
                        active_position.entry_commission_paid += entry_comm

                pending_order = None

            # -----------------------------------------------------------------
            # 2. ADIM: AÇIK POZİSYON ÇIKIŞ & YÖNETİM DENETİMİ (Stop, Scale-Out, Piramitleme)
            # -----------------------------------------------------------------
            if active_position is not None and active_position.is_active:
                sub_hourly = active_df.iloc[:t+1]
                sub_daily = daily_df[daily_df["timestamp"] <= current_time]

                required_margin = abs(active_position.lots) * initial_margin_per_contract
                free_margin = max(0.0, capital - required_margin)

                tech_res = self.executioner.evaluate(
                    symbol=symbol,
                    compass_bias=DirectionalBias.ONLY_LONG if active_position.lots > 0 else DirectionalBias.ONLY_SHORT,
                    daily_data=sub_daily if not sub_daily.empty else daily_df.iloc[:50],
                    hourly_data=sub_hourly,
                    position_state=active_position,
                    portfolio_nav=capital,
                    free_margin=free_margin
                )

                # A. BEDAVA PİRAMİTLEME (+2.0R Kârda %33 Ek Lot Emri)
                if tech_res.action == ExecutionActionV4.PYRAMID_ADD_33:
                    pending_order = {
                        "side": "LONG" if active_position.lots > 0 else "SHORT",
                        "lots": tech_res.target_lots,
                        "stop_price": active_position.trailing_stop,
                        "action": tech_res.action,
                        "is_pyramid": True
                    }

                # B. KISMİ KAPATMA (SCALE-OUT %33 veya %50)
                elif tech_res.action in (ExecutionActionV4.SCALE_OUT_33, ExecutionActionV4.SCALE_OUT_50):
                    closed_lots = tech_res.target_lots
                    is_long = active_position.lots > 0
                    
                    if is_long:
                        exit_price = round(current_close * (1.0 - self.SLIPPAGE_RATE), 2)
                        realized_pnl = (exit_price - active_position.entry_price) * closed_lots * contract_multiplier
                    else:
                        exit_price = round(current_close * (1.0 + self.SLIPPAGE_RATE), 2)
                        realized_pnl = (active_position.entry_price - exit_price) * closed_lots * contract_multiplier

                    # Çift taraflı komisyon: Satış Bacağı (Exit)
                    exit_notional = exit_price * closed_lots * contract_multiplier
                    exit_comm_rate = self.get_midas_commission_rate(cumulative_traded_volume_try) if self.use_midas_commission else self.DEFAULT_COMMISSION_RATE
                    exit_comm = exit_notional * exit_comm_rate
                    cumulative_traded_volume_try += exit_notional
                    total_commissions_paid += exit_comm

                    # Alış bacağından kapatılan paya düşen giriş komisyonu
                    tot_active_lots = abs(active_position.lots)
                    allocated_entry_comm = (closed_lots / tot_active_lots) * active_position.entry_commission_paid if tot_active_lots > 0 else 0.0
                    active_position.entry_commission_paid = max(0.0, active_position.entry_commission_paid - allocated_entry_comm)

                    total_trade_comm = allocated_entry_comm + exit_comm
                    slip = abs(exit_price - current_close) * closed_lots * contract_multiplier
                    total_slippage_paid += slip

                    # Net PnL (exit_price zaten kaymayı içerdiğinden slip tekrar düşülmez)
                    net_pnl = realized_pnl - total_trade_comm
                    capital += (realized_pnl - exit_comm)
                    trade_counter += 1

                    # Kalan pozisyon durumunu güncelle
                    if is_long:
                        active_position.lots -= closed_lots
                    else:
                        active_position.lots += closed_lots
                    active_position.scaled_out = True
                    if tech_res.stop_price > 0:
                        active_position.trailing_stop = tech_res.stop_price

                    r_realized = (
                        (exit_price - active_position.entry_price) / active_position.r_unit_price
                        if active_position.r_unit_price > 0 else 2.0
                    )
                    notional_val = round(closed_lots * contract_multiplier * active_position.entry_price, 2)
                    margin_val = round(closed_lots * initial_margin_per_contract, 2)
                    lev = round(notional_val / margin_val, 2) if margin_val > 0 else 1.0

                    completed_trades.append(TradeRecord(
                        trade_id=trade_counter,
                        symbol=symbol,
                        side="LONG" if is_long else "SHORT",
                        entry_time=active_position.entry_time or current_time,
                        exit_time=current_time,
                        entry_price=active_position.entry_price,
                        exit_price=exit_price,
                        lots=closed_lots,
                        initial_stop=active_position.initial_stop,
                        r_unit=active_position.r_unit_price,
                        realized_pnl=round(net_pnl, 2),
                        commission_paid=round(total_trade_comm, 2),
                        entry_commission=round(allocated_entry_comm, 2),
                        exit_commission=round(exit_comm, 2),
                        slippage_paid=round(slip, 2),
                        exit_reason=tech_res.action.value,
                        r_multiple_realized=round(r_realized, 2),
                        bars_held=active_position.bars_held,
                        notional_value=notional_val,
                        leverage=lev,
                        margin_used=margin_val,
                        is_pyramid=active_position.is_pyramided
                    ))

                # C. TAM KAPATMA (ZAMAN STOPU, CHANDELIER EXIT, TREND REVERSAL VEYA CUMA KAPANIŞI)
                elif tech_res.action in (
                    ExecutionActionV4.TIME_STOP_EXIT,
                    ExecutionActionV4.CHANDELIER_STOP_EXIT,
                    ExecutionActionV4.TREND_REVERSAL_EXIT,
                    ExecutionActionV4.FRIDAY_CLOSE_EXIT
                ):
                    closed_lots = abs(active_position.lots)
                    is_long = active_position.lots > 0
                    raw_exit = tech_res.stop_price if tech_res.stop_price > 0 else current_close

                    if is_long:
                        exit_price = round(raw_exit * (1.0 - self.SLIPPAGE_RATE), 2)
                        realized_pnl = (exit_price - active_position.entry_price) * closed_lots * contract_multiplier
                    else:
                        exit_price = round(raw_exit * (1.0 + self.SLIPPAGE_RATE), 2)
                        realized_pnl = (active_position.entry_price - exit_price) * closed_lots * contract_multiplier

                    # Çift taraflı komisyon: Satış Bacağı (Exit)
                    exit_notional = exit_price * closed_lots * contract_multiplier
                    exit_comm_rate = self.get_midas_commission_rate(cumulative_traded_volume_try) if self.use_midas_commission else self.DEFAULT_COMMISSION_RATE
                    exit_comm = exit_notional * exit_comm_rate
                    cumulative_traded_volume_try += exit_notional
                    total_commissions_paid += exit_comm

                    allocated_entry_comm = active_position.entry_commission_paid
                    total_trade_comm = allocated_entry_comm + exit_comm

                    slip = abs(exit_price - raw_exit) * closed_lots * contract_multiplier
                    total_slippage_paid += slip
                    net_pnl = realized_pnl - total_trade_comm
                    capital += (realized_pnl - exit_comm)
                    trade_counter += 1

                    r_realized = (
                        (exit_price - active_position.entry_price) / active_position.r_unit_price
                        if active_position.r_unit_price > 0 else 0.0
                    )
                    notional_val = round(closed_lots * contract_multiplier * active_position.entry_price, 2)
                    margin_val = round(closed_lots * initial_margin_per_contract, 2)
                    lev = round(notional_val / margin_val, 2) if margin_val > 0 else 1.0

                    completed_trades.append(TradeRecord(
                        trade_id=trade_counter,
                        symbol=symbol,
                        side="LONG" if is_long else "SHORT",
                        entry_time=active_position.entry_time or current_time,
                        exit_time=current_time,
                        entry_price=active_position.entry_price,
                        exit_price=exit_price,
                        lots=closed_lots,
                        initial_stop=active_position.initial_stop,
                        r_unit=active_position.r_unit_price,
                        realized_pnl=round(net_pnl, 2),
                        commission_paid=round(total_trade_comm, 2),
                        entry_commission=round(allocated_entry_comm, 2),
                        exit_commission=round(exit_comm, 2),
                        slippage_paid=round(slip, 2),
                        exit_reason=tech_res.action.value,
                        r_multiple_realized=round(r_realized, 2),
                        bars_held=active_position.bars_held,
                        notional_value=notional_val,
                        leverage=lev,
                        margin_used=margin_val,
                        is_pyramid=active_position.is_pyramided
                    ))

                    active_position = None

            # -----------------------------------------------------------------
            # 3. ADIM: YENİ GİRİŞ SİNYALİ ARAMA (Pozisyon Yoksa)
            # -----------------------------------------------------------------
            if active_position is None and pending_order is None and not circuit_breaker_active:
                sub_hourly = active_df.iloc[:t+1]
                # Sadece bugünden önceki TAMAMLANMIŞ günlük barları al (Zero Lookahead Bias)
                bar_d = current_time.date() if hasattr(current_time, "date") else current_time
                if hasattr(daily_df["timestamp"], "dt"):
                    sub_daily = daily_df[daily_df["timestamp"].dt.date < bar_d]
                else:
                    sub_daily = daily_df[daily_df["timestamp"] < current_time]

                # Tamamlanmış en az 20 günlük bar yoksa yeni sinyal aranmaz (geleceğe ait iloc[:50] sızıntısı engellenir)
                if len(sub_daily) < 20:
                    continue

                # Kademe 1: Mikroyapı Filtresi (ADV & Volume)
                is_index = (channel == AssetChannel.INDEX) or ("XU" in symbol) or ("XBANK" in symbol) or ("XUSIN" in symbol) or ("XHOLD" in symbol) or ("XGMYO" in symbol)
                is_fx = (channel == AssetChannel.FX)
                is_comm = (channel == AssetChannel.COMMODITY)
                hourly_vol_try = current_close * float(current_bar["volume"])

                if is_index:
                    default_adv = 1_500_000_000.0
                    default_oi = 250_000
                elif is_fx:
                    default_adv = 500_000_000.0
                    default_oi = 80_000
                elif is_comm:
                    default_adv = 200_000_000.0
                    default_oi = 50_000
                else:
                    default_adv = 80_000_000.0
                    default_oi = 25_000

                micro = MarketMicrostructureInput(
                    adv_try=max(default_adv, hourly_vol_try * 8.0),
                    open_interest_contracts=default_oi
                )
                carry = CostOfCarryInput(implied_irr=0.48, tcmb_funding_rate=0.50)

                # Kademe 2 & 3: Temel Pusula Yön İzni
                compass_multiplier = 1.0
                if override_directional_bias is not None:
                    bias = override_directional_bias
                else:
                    c_verdict, _ = self.compass.get_compass_verdict(
                        channel=channel,
                        micro=micro,
                        carry=carry,
                        fundamental_data=fundamental_data,
                        tcmb_policy_rate=0.50
                    )
                    dir_str = c_verdict.get("direction", "NEUTRAL") if isinstance(c_verdict, dict) else str(c_verdict)
                    bias = DirectionalBias(dir_str) if dir_str in DirectionalBias.__members__ else DirectionalBias.NEUTRAL
                    compass_multiplier = float(c_verdict.get("multiplier", 1.0)) if isinstance(c_verdict, dict) else 1.0

                if bias == DirectionalBias.NEUTRAL or compass_multiplier <= 0.0:
                    compass_neutral_bars += 1

                # Teknik İcra Motoru Değerlendirmesi (Dual Engine)
                free_margin = capital
                decision = self.executioner.evaluate(
                    symbol=symbol,
                    compass_bias=bias,
                    daily_data=sub_daily,
                    hourly_data=sub_hourly,
                    position_state=None,
                    portfolio_nav=capital,
                    free_margin=free_margin,
                    compass_multiplier=compass_multiplier
                )

                if decision.action in (
                    ExecutionActionV4.ENTER_LONG,
                    ExecutionActionV4.ENTER_LONG_B_TYPE,
                    ExecutionActionV4.ENTER_LONG_A_TYPE,
                    ExecutionActionV4.ENTER_BREAKAWAY_GAP,
                    ExecutionActionV4.ENTER_SHORT,
                    ExecutionActionV4.ENTER_SHORT_B_TYPE,
                    ExecutionActionV4.ENTER_SHORT_A_TYPE
                ):
                    pending_order = {
                        "side": "LONG" if decision.action in (
                            ExecutionActionV4.ENTER_LONG,
                            ExecutionActionV4.ENTER_LONG_B_TYPE,
                            ExecutionActionV4.ENTER_LONG_A_TYPE,
                            ExecutionActionV4.ENTER_BREAKAWAY_GAP
                        ) else "SHORT",
                        "lots": decision.target_lots,
                        "stop_price": decision.stop_price,
                        "signal_time": current_time,
                        "is_pyramid": False
                    }

            # Mark-to-Market Total Equity / NAV ve Drawdown Takibi
            unrealized_pnl_close = 0.0
            if active_position is not None and active_position.is_active:
                if active_position.lots > 0:
                    unrealized_pnl_close = (current_close - active_position.entry_price) * active_position.lots * contract_multiplier
                else:
                    unrealized_pnl_close = (active_position.entry_price - current_close) * abs(active_position.lots) * contract_multiplier
            current_nav_close = capital + unrealized_pnl_close

            if current_nav_close > peak_capital:
                peak_capital = current_nav_close
            dd_try = peak_capital - current_nav_close
            dd_pct = (dd_try / peak_capital) * 100.0 if peak_capital > 0 else 0.0

            if dd_try > max_drawdown_try:
                max_drawdown_try = dd_try
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct

        # ---------------------------------------------------------------------
        # 3.5. ADIM: DÖNEM SONU AÇIK POZİSYON TASFİYESİ (Mark-to-Market Closeout)
        # ---------------------------------------------------------------------
        if active_position is not None and active_position.is_active:
            closed_lots = abs(active_position.lots)
            is_long = active_position.lots > 0
            final_bar = active_df.iloc[-1]
            final_close = float(final_bar["close"])
            final_time = final_bar["timestamp"]

            if is_long:
                exit_price = round(final_close * (1.0 - self.SLIPPAGE_RATE), 2)
                realized_pnl = (exit_price - active_position.entry_price) * closed_lots * contract_multiplier
            else:
                exit_price = round(final_close * (1.0 + self.SLIPPAGE_RATE), 2)
                realized_pnl = (active_position.entry_price - exit_price) * closed_lots * contract_multiplier

            exit_notional = exit_price * closed_lots * contract_multiplier
            exit_comm_rate = self.get_midas_commission_rate(cumulative_traded_volume_try) if self.use_midas_commission else self.DEFAULT_COMMISSION_RATE
            exit_comm = exit_notional * exit_comm_rate
            total_commissions_paid += exit_comm
            slip = abs(exit_price - final_close) * closed_lots * contract_multiplier
            total_slippage_paid += slip

            allocated_entry_comm = active_position.entry_commission_paid
            total_trade_comm = allocated_entry_comm + exit_comm
            net_pnl = realized_pnl - total_trade_comm
            capital += (realized_pnl - exit_comm)
            trade_counter += 1

            r_realized = (
                (exit_price - active_position.entry_price) / active_position.r_unit_price
                if active_position.r_unit_price > 0 else 0.0
            )
            notional_val = round(closed_lots * contract_multiplier * active_position.entry_price, 2)
            margin_val = round(closed_lots * initial_margin_per_contract, 2)
            lev = round(notional_val / margin_val, 2) if margin_val > 0 else 1.0

            completed_trades.append(TradeRecord(
                trade_id=trade_counter,
                symbol=symbol,
                side="LONG" if is_long else "SHORT",
                entry_time=active_position.entry_time or final_time,
                exit_time=final_time,
                entry_price=active_position.entry_price,
                exit_price=exit_price,
                lots=closed_lots,
                initial_stop=active_position.initial_stop,
                r_unit=active_position.r_unit_price,
                realized_pnl=round(net_pnl, 2),
                commission_paid=round(total_trade_comm, 2),
                entry_commission=round(allocated_entry_comm, 2),
                exit_commission=round(exit_comm, 2),
                slippage_paid=round(slip, 2),
                exit_reason="END_OF_BACKTEST_CLOSEOUT",
                r_multiple_realized=round(r_realized, 2),
                bars_held=active_position.bars_held,
                notional_value=notional_val,
                leverage=lev,
                margin_used=margin_val,
                is_pyramid=active_position.is_pyramided
            ))
            active_position = None

        # ---------------------------------------------------------------------
        # 4. ADIM: PERFORMANS METRİKLERİ VE TEARSHEET
        # ---------------------------------------------------------------------
        total_trades = len(completed_trades)
        winning_trades = [tr for tr in completed_trades if tr.realized_pnl > 0]
        losing_trades = [tr for tr in completed_trades if tr.realized_pnl <= 0]

        win_count = len(winning_trades)
        lose_count = len(losing_trades)
        win_rate = (win_count / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = sum(tr.realized_pnl for tr in winning_trades)
        gross_loss = abs(sum(tr.realized_pnl for tr in losing_trades))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        total_net_pnl = capital - self.initial_capital
        total_return_pct = (total_net_pnl / self.initial_capital) * 100.0
        avg_r = (sum(tr.r_multiple_realized for tr in completed_trades) / total_trades) if total_trades > 0 else 0.0

        return BacktestTearsheet(
            initial_capital=self.initial_capital,
            final_capital=round(capital, 2),
            total_net_pnl=round(total_net_pnl, 2),
            total_return_pct=round(total_return_pct, 2),
            max_drawdown_pct=round(max_drawdown_pct, 2),
            max_drawdown_try=round(max_drawdown_try, 2),
            win_rate_pct=round(win_rate, 2),
            total_trades=total_trades,
            winning_trades=win_count,
            losing_trades=lose_count,
            profit_factor=round(profit_factor, 2),
            avg_r_multiple=round(avg_r, 2),
            total_commissions=round(total_commissions_paid, 2),
            total_slippage=round(total_slippage_paid, 2),
            compass_neutral_bars=compass_neutral_bars,
            trades=completed_trades
        )
