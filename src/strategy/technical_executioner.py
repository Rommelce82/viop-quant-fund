"""
VİOP Teknik İcra ve Otorite Anayasası (v4.0 - Ali Perşembe Doktrini & Dual Engine).

Rol: Nihai Karar Mercii, Zamanlama (Timing) ve Risk Yönetimi.
Yetki Sınırı: Temel Pusula'dan gelen yön iznine göre tetiği çeker, Lot hesaplar ve pozisyonu yönetir.
Tüm mutlak risk yönetimi bu modüldedir.

Kurallar & Şartname:
1. Piyasa Rejimi ve ADX/DMI Esnekliği (Dual Engine):
   - ADX Testere Kalkanı: Donchian kanal kırılımına hacim teyidi eşlik ediyorsa ve ΔADX > 0 ise,
     ADX alt eşiği 15.0'a çekilir.
   - Dual Engine (Karma Strateji):
     * ADX >= 15.0 ve ΔADX > 0 (veya ADX >= 20.0): B-Tarzı (Kırılım / Breakout).
     * ADX < 15.0 (veya yatay rejimde): A-Tarzı (Kanal İçi Destek/Direnç Tepkisi / Ortalamaya Dönüş).
   - Saatlik Volatilite Kısıtı (ATR / Close):
     * Endeks kontratlarında %1.5, hisse kontratlarında %4.5.
     * Yüksek volatilitede işlem yasaklanmak yerine lot miktarı küçültülür (vol_scale).
2. LONG İşlem Şartları:
   - Üst Vade: Günlük Close > SMA100 (veya Erken Dip Dönüşü: EMA20 > EMA50 ile 0.5x bütçe).
   - Alt Vade (120m / 60m):
     * B-Tarzı: Close >= High20 (Donchian Üst Kanalı, shift 1).
     * A-Tarzı: Close <= Bollinger Alt / EMA20 desteği ve yeşil boğa dönüş mumu (Close > Open).
   - Hacim: Hisse >= 1.40x SMA20(Vol), Endeks >= 1.15x SMA20(Vol).
   - Fitil: Normal bar üst fitil <= %40, genişleme barı (Range > 2.0x ATR) <= %55 (endeks %65).
3. SHORT İşlem Şartları:
   - Üst Vade: Günlük Close < SMA100 (Ayı Rejimi).
   - Alt Vade:
     * B-Tarzı: Close <= Low20 (Donchian Alt Kanalı, shift 1).
     * A-Tarzı: Close >= Bollinger Üst / EMA20 direnci ve kırmızı ayı dönüş mumu (Close < Open).
   - Hacim: Alıcısız çöküş prensibiyle Vol >= 1.00x SMA20(Vol).
   - Fitil: Düşüş mumu alt fitil <= %50.
4. Çıkış & Stop Yönetimi:
   - Initial Stop: Entry - (2.0 x ATR14) [Long] / Entry + (2.0 x ATR14) [Short].
   - Breakeven (Tapi): +1.0R kârda stop seviyesi Entry - 0.5 x ATR (Long) / Entry + 0.5 x ATR (Short).
   - Kademeli Kâr Satışı (%33 Scale-Out): +2.0R kârda pozisyonun %33'ü kapatılır, kalan taşınır.
   - Chandelier İz Süren Stop: 2.5x ATR iz süren stop (asla geriye çekilmez).
   - Zaman Stopu: 30 bar. Pozisyon kârdaysa (r_mult > 0) zaman stopu dondurulur.
   - Kesin Çıkış (Trend Reversal): Fiyat SMA20 altında/üstünde 2 ardışık bar kapattığında veya Günlük SMA100 ihlalinde koşulsuz kapatma.
5. Varlık Sınıfı Bazlı Düzenlemeler:
   - Endeks: Çift Yönlü B-Tarzı, Hacim 1.15x, Hedef min 1.5 R/K.
   - Hisse: Çift Yönlü Karma (A + B Tarzı), Hacim Long 1.40x, Short 1.00x, Hedef min 2.0 R/K.
   - Emtia: Çift Yönlü Trend, 2.5x Chandelier ile uzun taşıma.
   - Döviz (USDTRY, EURTRY, GBPTRY): Çıplak Breakout KAPALI (REJECT_FX_CARRY_ONLY). Sadece Carry / Zımni Faiz.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Dict, Optional, Tuple
import pandas as pd

from src.core.config import SystemConfig
from src.strategy.fundamental_compass import DirectionalBias
from src.strategy.indicators import (
    calculate_adx_dmi,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_diosc,
    calculate_donchian_channels,
    calculate_ema,
    calculate_rsi,
    calculate_sma
)
from src.strategy.position_manager import PositionState


class TechnicalRegime(str, Enum):
    """Teknik Piyasa Rejimi."""
    TRENDING = "TRENDING"
    RANGE_BOUND = "RANGE_BOUND"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


class ExecutionActionV4(str, Enum):
    """İcra Aksiyonu."""
    HOLD = "HOLD"
    ENTER_LONG = "ENTER_LONG"
    ENTER_LONG_B_TYPE = "ENTER_LONG_B_TYPE"     # B-Tarzı Breakout Long
    ENTER_LONG_A_TYPE = "ENTER_LONG_A_TYPE"     # A-Tarzı Mean-Reversion Long
    ENTER_SHORT = "ENTER_SHORT"
    ENTER_SHORT_B_TYPE = "ENTER_SHORT_B_TYPE"   # B-Tarzı Breakout Short
    ENTER_SHORT_A_TYPE = "ENTER_SHORT_A_TYPE"   # A-Tarzı Mean-Reversion Short
    ENTER_BREAKAWAY_GAP = "ENTER_BREAKAWAY_GAP" # Kaçış Boşluğu (Breakaway Gap) ile Katılım (0.75x bütçe)
    PYRAMID_ADD_33 = "PYRAMID_ADD_33"           # Bedava Piramitleme (+2.0R kârda %33 ek lot)
    SCALE_OUT_33 = "SCALE_OUT_33"
    SCALE_OUT_50 = "SCALE_OUT_50"
    TIME_STOP_EXIT = "TIME_STOP_EXIT"
    CHANDELIER_STOP_EXIT = "CHANDELIER_STOP_EXIT"
    TREND_REVERSAL_EXIT = "TREND_REVERSAL_EXIT"
    FRIDAY_CLOSE_EXIT = "FRIDAY_CLOSE_EXIT"          # Ali Perşembe: Cuma 17:45 çıkışı (<1.0R)
    REJECT_RISK_REWARD = "REJECT_RISK_REWARD"
    REJECT_MARGIN = "REJECT_MARGIN"
    REJECT_TESTERE_ADX_DUSUK = "REJECT_TESTERE_ADX_DUSUK"  # Ali Perşembe: Sert Testere Kalkanı (ADX < 20)
    REJECT_GAP_LARGE = "REJECT_GAP_LARGE"                  # Ali Perşembe: Kapanmayan Tehlikeli Gap > %2.5
    REJECT_WICK_EXCESSIVE = "REJECT_WICK_EXCESSIVE"        # Ali Perşembe: Fitil (Wick) Reddi
    REJECT_INSIDE_BAR = "REJECT_INSIDE_BAR"                # Ali Perşembe: Inside Bar
    REJECT_TIME_OPENING = "REJECT_TIME_OPENING"            # Ali Perşembe: Saat 09:30-10:15 açılış çalkantısı
    REJECT_SMA20_STRETCH = "REJECT_SMA20_STRETCH"          # Ali Perşembe: Fiyat SMA20'den > %15 uzaklaşmış
    REJECT_KAP_NEWS = "REJECT_KAP_NEWS"                    # Ali Perşembe: O barda KAP haberi var
    REJECT_TREND_EXHAUSTION = "REJECT_TREND_EXHAUSTION"    # Ali Perşembe: ADX > 50 ve aşağı dönmüş (Yorgunluk)
    REJECT_DIOSC_BEARISH = "REJECT_DIOSC_BEARISH"          # Ali Perşembe: DIOSC teyidi yok (Long için < SMA9)
    REJECT_DIOSC_BULLISH = "REJECT_DIOSC_BULLISH"          # Ali Perşembe: DIOSC teyidi yok (Short için > SMA9)
    REJECT_FX_CARRY_ONLY = "REJECT_FX_CARRY_ONLY"          # Ali Perşembe: TRY kurunda çıplak kırılım kapalı


@dataclass
class TechnicalDecisionV4:
    """Nihai Teknik Karar ve Emir Detayı."""
    action: ExecutionActionV4
    symbol: str
    target_lots: int
    entry_price: float
    stop_price: float
    take_profit_target: float
    expected_rr_ratio: float
    reason: str
    metrics: Dict[str, any]


class TechnicalExecutioner:
    """
    VİOP Teknik İcra ve Mutlak Otorite Motoru (v4.0 - Ali Perşembe Doktrini & Dual Engine).
    """

    MIN_RR_RATIO = 2.0              # Minimum 2.0 R/K Barajı (Endeks için dinamik 1.5)
    RISK_BUDGET_PCT = 0.02          # %2 NAV Riski
    TIME_STOP_BARS = 30             # 30 Saat (Yaklaşık 4 Borsa Günü)
    CHANDELIER_ATR_MULT = 2.5       # 2.5x ATR İz Süren Stop
    INITIAL_STOP_ATR_MULT = 2.0     # 2.0x ATR İlk Stop Mesafesi

    def __init__(self, config: Optional[SystemConfig] = None, time_stop_bars: int = 30) -> None:
        self.config = config or SystemConfig()
        self.TIME_STOP_BARS = time_stop_bars
        self.NO_TRADE_FX = ["F_USDTRY", "F_EURTRY", "F_GBPTRY", "F_DXY", "F_EURUSD"]

    def get_asset_class(self, symbol: str) -> str:
        """Sözleşmenin varlık sınıfını tespit eder."""
        if any(idx in symbol for idx in ("XU", "XBANK", "XLBNK", "XUSIN", "XHOLD", "XGMYO")):
            return "INDEX"
        if ("TRY" in symbol or "TRY=X" in symbol) and any(c in symbol for c in ("USD", "EUR", "GBP")):
            return "FX_TRY"
        if any(fx in symbol for fx in ("EURUSD", "DXY", "DX-Y")):
            return "FX_GLOBAL"
        if any(cm in symbol for cm in ("XAU", "XAG", "GC", "SI", "BZ", "BRENT", "PL", "PLAT", "HG", "COPPER")):
            return "COMMODITY"
        return "EQUITY"

    def get_dynamic_atr_multiplier(self, latest_adx: float, is_adx_rising: bool) -> float:
        """
        Ali Perşembe Doktrini - Dinamik ATR Çarpanı (Volatilite ve Trend Gücüne Göre):
        - ADX >= 25 ve ADX Eğimi > 0 (Güçlü Trend): atr_multiplier = 3.0
        - 20 <= ADX < 25 (Normal Trend): atr_multiplier = 2.5
        - ADX < 20: atr_multiplier = 2.0 (İlk zarar stopu tabanı)
        """
        if latest_adx >= 25.0 and is_adx_rising:
            return 3.0
        elif 20.0 <= latest_adx:
            return 2.5
        else:
            return 2.0

    def detect_regime(self, hourly_data: pd.DataFrame) -> Tuple[TechnicalRegime, Dict[str, float]]:
        """
        Saatlik veride rejim tespiti:
        - TRENDING: (ADX >= 20 AND yükseliyor) VEYA (ADX >= 15 AND yükseliyor) VEYA (ADX >= 25)
        - RANGE_BOUND: Diğer durumlar
        """
        if hourly_data.empty or len(hourly_data) < 16:
            return TechnicalRegime.RANGE_BOUND, {"adx": 0.0, "atr_ratio": 0.0, "is_adx_rising": False}

        close_series = hourly_data["close"]
        current_close = float(close_series.iloc[-1])
        atr_series = calculate_atr(hourly_data, period=14)
        current_atr = float(atr_series.iloc[-1])
        atr_ratio = current_atr / current_close if current_close > 0 else 0.0

        adx, plus_di, minus_di = calculate_adx_dmi(hourly_data, period=14)
        latest_adx = float(adx.iloc[-1])
        prev_adx = float(adx.iloc[-2]) if len(adx) >= 2 else latest_adx
        is_adx_rising = latest_adx > prev_adx

        if (latest_adx >= 20.0 and is_adx_rising) or (latest_adx >= 15.0 and is_adx_rising) or (latest_adx >= 25.0):
            regime = TechnicalRegime.TRENDING
        else:
            regime = TechnicalRegime.RANGE_BOUND

        return regime, {
            "adx": latest_adx,
            "prev_adx": prev_adx,
            "is_adx_rising": is_adx_rising,
            "atr": current_atr,
            "atr_ratio": atr_ratio
        }

    def calculate_lot_size_with_margin_cap(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        portfolio_nav: float,
        free_margin: float,
        compass_multiplier: float = 1.0
    ) -> Tuple[int, str]:
        """
        Ali Perşembe Doktrini - Dinamik Lot Formülü:
        Lot = FLOOR( ((Portföy_NAV * 0.02) / ((Giriş_Fiyatı - Stop_Fiyatı) * Sözleşme_Çarpanı)) * Pusula_Multiplier )
        """
        if compass_multiplier <= 0.0:
            return 0, f"Pusula/Volatilite çarpanı sıfır ({compass_multiplier:.2f}). İşlem bloklandı."

        spec = self.config.contracts.get(symbol)
        multiplier = spec.multiplier if spec else 100.0
        initial_margin_per_contract = spec.initial_margin_try if spec else 6500.0

        risk_distance = abs(entry_price - stop_price)
        if risk_distance <= 0.0:
            return 0, "Stop mesafesi sıfır."

        # %2 NAV kuralı ile temel lot * Dinamik Çarpan
        risk_budget_try = portfolio_nav * self.RISK_BUDGET_PCT
        risk_per_contract = risk_distance * multiplier
        raw_ideal_lots = (risk_budget_try / risk_per_contract) * compass_multiplier
        ideal_lots = math.floor(raw_ideal_lots)

        # Asgari 1 Lot Güvencesi: Küçük kasalarda risk NAV'ın %3.5'ini aşmıyorsa 1 lot ver
        if ideal_lots <= 0:
            max_allowed_risk = portfolio_nav * 0.035
            if risk_per_contract <= max_allowed_risk and free_margin >= initial_margin_per_contract:
                ideal_lots = 1
            else:
                return 0, f"Risk bütçesi veya dinamik çarpan ({compass_multiplier:.2f}) 1 lota yetmiyor."

        # Serbest Teminat (Free Margin) Tıraşlaması
        max_lots_by_margin = math.floor(free_margin / initial_margin_per_contract)

        if max_lots_by_margin <= 0:
            return 0, f"Yetersiz Serbest Teminat: {free_margin:,.2f} TL (Gerekli: {initial_margin_per_contract:,.2f} TL)."

        if ideal_lots > max_lots_by_margin:
            capped_lots = max_lots_by_margin
            return capped_lots, (
                f"Teminat Tıraşlaması (Margin Cap): Bütçe {ideal_lots} lot önerdi (Çarpan: {compass_multiplier:.2f}), "
                f"ancak serbest teminat ({free_margin:,.2f} TL) nedeniyle {capped_lots} lota tıraşlandı."
            )
        else:
            return ideal_lots, f"Risk bütçesi onaylandı ({ideal_lots} lot, Dinamik Çarpan: {compass_multiplier:.2f})."

    def evaluate(
        self,
        symbol: str,
        compass_bias: any,
        daily_data: pd.DataFrame,
        hourly_data: pd.DataFrame,
        position_state: Optional[PositionState],
        portfolio_nav: float,
        free_margin: float,
        compass_multiplier: Optional[float] = None,
        has_kap_news: bool = False,
        current_time_override: Optional[datetime] = None
    ) -> TechnicalDecisionV4:
        """
        Teknik İcra, Dual Engine (A/B Tarzı) ve Risk Yönetimi Değerlendirmesi.
        """
        # Dict veya Enum ayrıştırma
        if isinstance(compass_bias, dict):
            raw_dir = compass_bias.get("direction", "NEUTRAL")
            dir_bias = DirectionalBias(raw_dir) if raw_dir in DirectionalBias.__members__ else DirectionalBias.NEUTRAL
            eff_multiplier = float(compass_bias.get("multiplier", 1.0))
        elif isinstance(compass_bias, DirectionalBias):
            dir_bias = compass_bias
            eff_multiplier = 1.0 if compass_multiplier is None else compass_multiplier
        else:
            dir_bias = DirectionalBias.NEUTRAL
            eff_multiplier = 0.0

        if compass_multiplier is not None:
            eff_multiplier = float(compass_multiplier)

        current_bar = hourly_data.iloc[-1]
        current_price = float(current_bar["close"])
        bar_timestamp = current_time_override or current_bar.get("timestamp")
        if isinstance(bar_timestamp, str):
            bar_timestamp = pd.to_datetime(bar_timestamp)

        hourly_atr = float(calculate_atr(hourly_data, period=14).iloc[-1])
        asset_class = self.get_asset_class(symbol)
        is_index = (asset_class == "INDEX")

        # ---------------------------------------------------------------------
        # 1. MEVCUT AÇIK POZİSYONUN ÇIKIŞ VE SIKILAŞTIRMA YÖNETİMİ
        # ---------------------------------------------------------------------
        if position_state and position_state.is_active:
            position_state.increment_bars_held()
            r_mult = position_state.get_current_r_multiple(current_price)

            # [KURAL]: Cuma Kapanışı (Cuma 17:45 ve sonrası sadece zararlı pozisyonlar kapatılır: r_mult <= 0.0)
            if bar_timestamp is not None and hasattr(bar_timestamp, "weekday"):
                is_friday = (bar_timestamp.weekday() == 4)
                time_float = bar_timestamp.hour + (bar_timestamp.minute / 60.0)
                if is_friday and time_float >= 17.75 and r_mult <= 0.0:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.FRIDAY_CLOSE_EXIT,
                        symbol=symbol,
                        target_lots=abs(position_state.lots),
                        entry_price=position_state.entry_price,
                        stop_price=current_price,
                        take_profit_target=0.0,
                        expected_rr_ratio=r_mult,
                        reason=f"Cuma Kapanışı: Cuma 17:45 sonrası kârsız pozisyon ({r_mult:.2f}R <= 0.0R) kapatıldı.",
                        metrics={"r_multiple": r_mult, "bar_time": str(bar_timestamp)}
                    )

            # [KURAL]: Zaman Stopu (bars_held >= TIME_STOP_BARS ve Kâr <= 0.0R)
            # Ali Perşembe Şartnamesi: Pozisyon kârdaysa (r_mult > 0) zaman stopu dondurulur!
            if position_state.bars_held >= self.TIME_STOP_BARS and r_mult <= 0.0:
                return TechnicalDecisionV4(
                    action=ExecutionActionV4.TIME_STOP_EXIT,
                    symbol=symbol,
                    target_lots=abs(position_state.lots),
                    entry_price=position_state.entry_price,
                    stop_price=current_price,
                    take_profit_target=0.0,
                    expected_rr_ratio=r_mult,
                    reason=f"Zaman Stopu: {self.TIME_STOP_BARS} saatlik bar geçti ve kâr {r_mult:.2f}R <= 0.0R. Zararlı pozisyon kapatıldı.",
                    metrics={"bars_held": position_state.bars_held, "r_multiple": r_mult}
                )

            # [KURAL]: Tapi (Breakeven) Retest Marjı: +1.0R kârda stop Giriş +- 0.5 ATR seviyesine çekilir
            if r_mult >= 1.0:
                position_state.is_breakeven_activated = True
                if position_state.lots > 0:
                    tapi_stop = round(position_state.entry_price - (0.5 * hourly_atr), 2)
                    if tapi_stop > position_state.trailing_stop:
                        position_state.trailing_stop = tapi_stop
                else:
                    tapi_stop = round(position_state.entry_price + (0.5 * hourly_atr), 2)
                    if tapi_stop < position_state.trailing_stop:
                        position_state.trailing_stop = tapi_stop

            # [KURAL]: Kademeli Kâr Satışı (%33 Scale-Out: Kâr >= 2.0R, %33 Kapat, %67 Trend Sürüşü)
            # Endekste ADX >= 25 ise sabit hedef yerine %67 Chandelier stop ihlaline kadar taşınır!
            if r_mult >= 2.0 and not position_state.scaled_out and abs(position_state.lots) > 1:
                close_qty = max(1, math.floor(abs(position_state.lots) * 0.33))
                new_stop = (
                    max(position_state.trailing_stop, position_state.entry_price - (0.5 * hourly_atr))
                    if position_state.lots > 0
                    else min(position_state.trailing_stop, position_state.entry_price + (0.5 * hourly_atr))
                )
                ride_msg = "Kalan %67 Chandelier stop ihlaline kadar trend sürüşünde tutuluyor." if is_index else "Stop güvenli maliyete çekildi."
                return TechnicalDecisionV4(
                    action=ExecutionActionV4.SCALE_OUT_33,
                    symbol=symbol,
                    target_lots=close_qty,
                    entry_price=position_state.entry_price,
                    stop_price=new_stop,
                    take_profit_target=0.0,
                    expected_rr_ratio=r_mult,
                    reason=f"Scale-Out (%33): +2.0R kâr seviyesine ({r_mult:.2f}R) ulaşıldı. Pozisyonun %33'ü ({close_qty} lot) kapatıldı. {ride_msg}",
                    metrics={"r_multiple": r_mult, "remaining_lots": abs(position_state.lots) - close_qty}
                )

            # [KURAL]: Bedava Piramitleme (Free Pyramiding - Kârlı Pozisyona Ekleme)
            # Pozisyon +2.0R kâra geçmiş, kâr realizasyonu yapılmış, stop maliyetin üzerinde (risk sıfır)
            # ve yeni bir 240m kırılımı gelmişse %33 ek lot açılır.
            if position_state.can_pyramid(r_mult):
                don_h_pyr, don_l_pyr, _ = calculate_donchian_channels(hourly_data, period=20)
                is_pyr_breakout = False
                if position_state.lots > 0 and current_price >= float(don_h_pyr.iloc[-1]):
                    is_pyr_breakout = True
                elif position_state.lots < 0 and current_price <= float(don_l_pyr.iloc[-1]):
                    is_pyr_breakout = True

                if is_pyr_breakout:
                    pyramid_qty = max(1, math.floor(abs(position_state.lots) * 0.33))
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.PYRAMID_ADD_33,
                        symbol=symbol,
                        target_lots=pyramid_qty,
                        entry_price=current_price,
                        stop_price=position_state.trailing_stop,
                        take_profit_target=0.0,
                        expected_rr_ratio=r_mult,
                        reason=f"Bedava Piramitleme (Free Pyramiding): Pozisyon {r_mult:.2f}R kârda, risk sıfır. Yeni 240m kırılımında %33 ({pyramid_qty} lot) ilave ekleme yapıldı.",
                        metrics={"pyramid_lots": pyramid_qty, "total_lots": abs(position_state.lots) + pyramid_qty, "r_multiple": r_mult}
                    )

            # [KURAL]: Kesin Çıkış Kuralları (SMA20 altında/üstünde 2 ardışık bar veya Günlük SMA100 ihlali)
            daily_sma_100_cur = float(daily_data["close"].rolling(window=100, min_periods=50).mean().iloc[-1])
            daily_close_cur = float(daily_data["close"].iloc[-1])
            sma20_hourly = calculate_sma(hourly_data["close"], period=20)

            if position_state.lots > 0:
                daily_rev = daily_close_cur < daily_sma_100_cur
                hourly_rev = False
                if len(hourly_data) >= 2:
                    c1 = float(hourly_data["close"].iloc[-1])
                    c2 = float(hourly_data["close"].iloc[-2])
                    s1 = float(sma20_hourly.iloc[-1])
                    s2 = float(sma20_hourly.iloc[-2])
                    hourly_rev = (c1 < s1 and c2 < s2)

                if daily_rev or hourly_rev:
                    rev_reason = "Günlük Close < SMA100 (Üst Vade Ayı Sinyali)" if daily_rev else "Fiyat SMA20 altında 2 ardışık bar kapattı"
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.TREND_REVERSAL_EXIT,
                        symbol=symbol,
                        target_lots=abs(position_state.lots),
                        entry_price=position_state.entry_price,
                        stop_price=current_price,
                        take_profit_target=0.0,
                        expected_rr_ratio=r_mult,
                        reason=f"Kesin Çıkış (Trend Reversal): {rev_reason}. Long pozisyon koşulsuz kapatıldı.",
                        metrics={"daily_close": daily_close_cur, "daily_sma100": daily_sma_100_cur, "r_multiple": r_mult}
                    )
            else:
                daily_rev = daily_close_cur > daily_sma_100_cur
                hourly_rev = False
                if len(hourly_data) >= 2:
                    c1 = float(hourly_data["close"].iloc[-1])
                    c2 = float(hourly_data["close"].iloc[-2])
                    s1 = float(sma20_hourly.iloc[-1])
                    s2 = float(sma20_hourly.iloc[-2])
                    hourly_rev = (c1 > s1 and c2 > s2)

                if daily_rev or hourly_rev:
                    rev_reason = "Günlük Close > SMA100 (Üst Vade Boğa Sinyali)" if daily_rev else "Fiyat SMA20 üzerinde 2 ardışık bar kapattı"
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.TREND_REVERSAL_EXIT,
                        symbol=symbol,
                        target_lots=abs(position_state.lots),
                        entry_price=position_state.entry_price,
                        stop_price=current_price,
                        take_profit_target=0.0,
                        expected_rr_ratio=r_mult,
                        reason=f"Kesin Çıkış (Trend Reversal): {rev_reason}. Short pozisyon koşulsuz kapatıldı.",
                        metrics={"daily_close": daily_close_cur, "daily_sma100": daily_sma_100_cur, "r_multiple": r_mult}
                    )

            # [KURAL]: Dinamik Chandelier Çarpanı Sıkılaştırması (Parabolik Ralli ve Trend Yorgunluğu)
            chandelier_mult = self.CHANDELIER_ATR_MULT  # Normal: 2.5x

            # A. Parabolik Ralli Kontrolü: Fiyat EMA20'den %10 uzaklaşmışsa stop 1.5 ATR'ye daraltılır
            ema20 = float(calculate_ema(hourly_data["close"], period=20).iloc[-1])
            if ema20 > 0 and abs(current_price - ema20) / ema20 >= 0.10:
                chandelier_mult = 1.5

            # B. Trend Yorgunluğu Kontrolü: ADX > 50 ve aşağı dönmüşse stop 1.5 ATR'ye daraltılır
            adx_s, _, _ = calculate_adx_dmi(hourly_data, period=14)
            latest_adx_val = float(adx_s.iloc[-1])
            prev_adx_val = float(adx_s.iloc[-2]) if len(adx_s) >= 2 else latest_adx_val
            if latest_adx_val > 50.0 and latest_adx_val < prev_adx_val:
                chandelier_mult = 1.5

            is_long = position_state.lots > 0
            if is_long:
                # 1. Bar başında geçerli olan trailing_stop ihlal edildi mi? (Zaman paradoksunu önlemek için)
                if current_bar["low"] <= position_state.trailing_stop:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.CHANDELIER_STOP_EXIT,
                        symbol=symbol,
                        target_lots=abs(position_state.lots),
                        entry_price=position_state.entry_price,
                        stop_price=position_state.trailing_stop,
                        take_profit_target=0.0,
                        expected_rr_ratio=r_mult,
                        reason=f"Chandelier Exit: Long iz süren stop ({position_state.trailing_stop} TL, Çarpan: {chandelier_mult}x) ihlal edildi. Kalan pozisyon kapatıldı.",
                        metrics={"trailing_stop": position_state.trailing_stop, "atr": hourly_atr, "mult": chandelier_mult}
                    )
                # İhlal edilmediyse, bu barın high seviyesinden sonraki barlar için geçerli olacak yeni iz süren stop hesaplanır
                chandelier_stop = round(current_bar["high"] - (chandelier_mult * hourly_atr), 2)
                if chandelier_stop > position_state.trailing_stop:
                    position_state.trailing_stop = chandelier_stop
            else:
                # Short için: Bar başında geçerli olan trailing_stop ihlal edildi mi?
                if current_bar["high"] >= position_state.trailing_stop:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.CHANDELIER_STOP_EXIT,
                        symbol=symbol,
                        target_lots=abs(position_state.lots),
                        entry_price=position_state.entry_price,
                        stop_price=position_state.trailing_stop,
                        take_profit_target=0.0,
                        expected_rr_ratio=r_mult,
                        reason=f"Chandelier Exit: Short iz süren stop ({position_state.trailing_stop} TL, Çarpan: {chandelier_mult}x) ihlal edildi. Kalan pozisyon kapatıldı.",
                        metrics={"trailing_stop": position_state.trailing_stop, "atr": hourly_atr, "mult": chandelier_mult}
                    )
                chandelier_stop = round(current_bar["low"] + (chandelier_mult * hourly_atr), 2)
                if chandelier_stop < position_state.trailing_stop:
                    position_state.trailing_stop = chandelier_stop

            # Pozisyon devam ediyor
            return TechnicalDecisionV4(
                action=ExecutionActionV4.HOLD,
                symbol=symbol,
                target_lots=abs(position_state.lots),
                entry_price=position_state.entry_price,
                stop_price=position_state.trailing_stop,
                take_profit_target=0.0,
                expected_rr_ratio=r_mult,
                reason=f"Pozisyon Korunuyor (Bar: {position_state.bars_held}, Kâr: {r_mult:.2f}R, Stop: {position_state.trailing_stop} TL, Çarpan: {chandelier_mult}x)",
                metrics={"bars_held": position_state.bars_held, "trailing_stop": position_state.trailing_stop, "chandelier_mult": chandelier_mult}
            )

        # ---------------------------------------------------------------------
        # 2. YENİ İŞLEME GİRİŞ DEĞERLENDİRMESİ
        # ---------------------------------------------------------------------
        if dir_bias == DirectionalBias.NEUTRAL or eff_multiplier <= 0.0:
            return TechnicalDecisionV4(
                action=ExecutionActionV4.HOLD,
                symbol=symbol,
                target_lots=0,
                entry_price=current_price,
                stop_price=0.0,
                take_profit_target=0.0,
                expected_rr_ratio=0.0,
                reason=f"Temel Pusula İzni Yok (Yön: {dir_bias.value}, Çarpan: {eff_multiplier}). İşlem bloklandı.",
                metrics={"compass_multiplier": eff_multiplier}
            )

        # [KURAL]: Döviz ve FX Çıplak Breakout Blokajı (USDTRY, EURTRY, GBPTRY, DXY, EURUSD)
        # Ali Perşembe Doktrini: Müdahaleli kur rejiminde kırılım zararı engellenir. Sadece Carry Arbitrajı / Zımni Faiz.
        if symbol in self.NO_TRADE_FX or asset_class in ("FX_TRY", "FX_GLOBAL"):
            return TechnicalDecisionV4(
                action=ExecutionActionV4.REJECT_FX_CARRY_ONLY,
                symbol=symbol,
                target_lots=0,
                entry_price=current_price,
                stop_price=0.0,
                take_profit_target=0.0,
                expected_rr_ratio=0.0,
                reason="REJECT_FX_CARRY_ONLY: Döviz VİOP ve FX (USDTRY, EURTRY, GBPTRY, DXY, EURUSD) kontratlarında çıplak kırılım KAPALI. Serbest nakit Akbank ALE Para Piyasası Fonu'nda (%48 brüt nema) nemalandırılır.",
                metrics={}
            )

        # [KURAL]: KAP Haberi Filtresi
        if has_kap_news:
            return TechnicalDecisionV4(
                action=ExecutionActionV4.REJECT_KAP_NEWS,
                symbol=symbol,
                target_lots=0,
                entry_price=current_price,
                stop_price=0.0,
                take_profit_target=0.0,
                expected_rr_ratio=0.0,
                reason="REJECT_KAP_NEWS: O barda KAP haberi açıklandı. Ani volatilite ve manipülasyon riskine karşı yeni giriş yasaklandı.",
                metrics={}
            )

        # [KURAL]: Saat 09:30-10:15 Açılış Çalkantısı Filtresi (09:30-10:15 Blokajı)
        if bar_timestamp is not None and hasattr(bar_timestamp, "hour"):
            time_decimal = bar_timestamp.hour + (bar_timestamp.minute / 60.0)
            if 9.5 <= time_decimal <= 10.25:
                return TechnicalDecisionV4(
                    action=ExecutionActionV4.REJECT_TIME_OPENING,
                    symbol=symbol,
                    target_lots=0,
                    entry_price=current_price,
                    stop_price=0.0,
                    take_profit_target=0.0,
                    expected_rr_ratio=0.0,
                    reason=f"REJECT_TIME_OPENING: Saat {bar_timestamp.strftime('%H:%M')} (09:30-10:15) açılış çalkantısı aralığında. Kırılım güvenilmez, işlem veto edildi.",
                    metrics={"time": str(bar_timestamp)}
                )

        # [KURAL]: Fiyat SMA20'den %15 Uzaklaşmışsa (Aşırı Gerilme / Mean Reversion Riski)
        sma20_val = float(calculate_sma(hourly_data["close"], period=20).iloc[-1])
        if sma20_val > 0:
            stretch_pct = abs(current_price - sma20_val) / sma20_val
            if stretch_pct >= 0.15:
                return TechnicalDecisionV4(
                    action=ExecutionActionV4.REJECT_SMA20_STRETCH,
                    symbol=symbol,
                    target_lots=0,
                    entry_price=current_price,
                    stop_price=0.0,
                    take_profit_target=0.0,
                    expected_rr_ratio=0.0,
                    reason=f"REJECT_SMA20_STRETCH: Fiyat SMA20'den %{stretch_pct*100:.1f} >= %15 uzaklaştı. Aşırı gerilme nedeniyle kırılım reddedildi.",
                    metrics={"stretch_pct": stretch_pct, "sma20": sma20_val}
                )

        # [KURAL]: Gap Kontrolü ve Kaçış Boşluğu (Breakaway Gap) Ayrıştırması
        is_breakaway_gap = False
        if len(hourly_data) >= 2:
            prev_bar_close = float(hourly_data["close"].iloc[-2])
            current_bar_open = float(current_bar["open"])
            if prev_bar_close > 0:
                raw_gap_ratio = (current_bar_open - prev_bar_close) / prev_bar_close
                if abs(raw_gap_ratio) > 0.025:
                    # Kaçış Boşluğu Teyidi (Ali Perşembe):
                    # Gap yönünde tutunma varsa 0.75x bütçe ile trend yönlü pozisyona katılım sağlanır.
                    is_gap_up_holding = (raw_gap_ratio > 0.025) and (current_price >= current_bar_open) and (dir_bias in (DirectionalBias.ONLY_LONG, DirectionalBias.BI_DIRECTIONAL))
                    is_gap_down_holding = (raw_gap_ratio < -0.025) and (current_price <= current_bar_open) and (dir_bias in (DirectionalBias.ONLY_SHORT, DirectionalBias.BI_DIRECTIONAL))

                    if is_gap_up_holding or is_gap_down_holding:
                        is_breakaway_gap = True
                        eff_multiplier *= 0.75  # Kaçış boşluğunda 0.75x bütçe çarpanı
                    else:
                        return TechnicalDecisionV4(
                            action=ExecutionActionV4.REJECT_GAP_LARGE,
                            symbol=symbol,
                            target_lots=0,
                            entry_price=current_price,
                            stop_price=0.0,
                            take_profit_target=0.0,
                            expected_rr_ratio=0.0,
                            reason=f"REJECT_GAP_LARGE: Gap %{abs(raw_gap_ratio)*100:.2f} > %2.5 ve Kaçış Boşluğu teyidi yok (kapanma eğilimi). Riskli işlem veto edildi.",
                            metrics={"gap_pct": raw_gap_ratio}
                        )

        # [KURAL]: Fitil (Wick) Kontrolü
        bar_high = float(current_bar["high"])
        bar_low = float(current_bar["low"])
        bar_open = float(current_bar["open"])
        bar_range = bar_high - bar_low
        is_expansion_bar = bar_range > (2.0 * hourly_atr)

        if bar_range > 0 and dir_bias in (DirectionalBias.ONLY_LONG, DirectionalBias.BI_DIRECTIONAL):
            upper_wick = bar_high - max(bar_open, current_price)
            upper_wick_ratio = upper_wick / bar_range
            wick_thresh = 0.65 if is_index else (0.55 if is_expansion_bar else 0.40)
            if upper_wick_ratio > wick_thresh:
                return TechnicalDecisionV4(
                    action=ExecutionActionV4.REJECT_WICK_EXCESSIVE,
                    symbol=symbol,
                    target_lots=0,
                    entry_price=current_price,
                    stop_price=0.0,
                    take_profit_target=0.0,
                    expected_rr_ratio=0.0,
                    reason=f"REJECT_WICK_EXCESSIVE: Kırılım barında Üst Fitil %{upper_wick_ratio*100:.1f} > %{wick_thresh*100:.0f}. Satıcı baskısı tespit edildi, Long veto edildi.",
                    metrics={"upper_wick_ratio": upper_wick_ratio}
                )

        if bar_range > 0 and dir_bias in (DirectionalBias.ONLY_SHORT, DirectionalBias.BI_DIRECTIONAL):
            lower_wick = min(bar_open, current_price) - bar_low
            lower_wick_ratio = lower_wick / bar_range
            if lower_wick_ratio > 0.50:
                return TechnicalDecisionV4(
                    action=ExecutionActionV4.REJECT_WICK_EXCESSIVE,
                    symbol=symbol,
                    target_lots=0,
                    entry_price=current_price,
                    stop_price=0.0,
                    take_profit_target=0.0,
                    expected_rr_ratio=0.0,
                    reason=f"REJECT_WICK_EXCESSIVE: Düşüş barında Alt Fitil %{lower_wick_ratio*100:.1f} > %50. Alıcı tepkisi tespit edildi, Short veto edildi.",
                    metrics={"lower_wick_ratio": lower_wick_ratio}
                )

        # [KURAL]: Inside Bar (İç Bar) Filtresi
        if len(hourly_data) >= 2:
            prev_high_val = float(hourly_data["high"].iloc[-2])
            prev_low_val = float(hourly_data["low"].iloc[-2])
            if bar_high <= prev_high_val and bar_low >= prev_low_val:
                return TechnicalDecisionV4(
                    action=ExecutionActionV4.REJECT_INSIDE_BAR,
                    symbol=symbol,
                    target_lots=0,
                    entry_price=current_price,
                    stop_price=0.0,
                    take_profit_target=0.0,
                    expected_rr_ratio=0.0,
                    reason="REJECT_INSIDE_BAR: Kırılım barı bir İç Bar (Inside Bar). Sıkışma çözülmeden işleme girilmez.",
                    metrics={}
                )

        # [KURAL]: Trend Yorgunluğu (ADX > 50 ve aşağı dönmüşse yeni giriş yasaklanır)
        adx_series, _, _ = calculate_adx_dmi(hourly_data, period=14)
        latest_adx = float(adx_series.iloc[-1])
        prev_adx = float(adx_series.iloc[-2]) if len(adx_series) >= 2 else latest_adx
        is_adx_rising = latest_adx > prev_adx

        if latest_adx > 50.0 and not is_adx_rising:
            return TechnicalDecisionV4(
                action=ExecutionActionV4.REJECT_TREND_EXHAUSTION,
                symbol=symbol,
                target_lots=0,
                entry_price=current_price,
                stop_price=0.0,
                take_profit_target=0.0,
                expected_rr_ratio=0.0,
                reason=f"REJECT_TREND_EXHAUSTION: ADX={latest_adx:.1f} > 50 ve aşağı döndü (Trend Yorgunluğu). Yeni pozisyon açılışı yasaklandı.",
                metrics={"adx": latest_adx}
            )

        # Saatlik Volatilite Kısıtı ve Lot Ölçekleme (vol_scale)
        # Endeks kontratlarında %1.5, hisse ve diğerlerinde %4.5. Yasaklamak yerine lot küçültülür.
        atr_ratio = hourly_atr / current_price if current_price > 0 else 0.0
        max_atr_ratio = 0.015 if is_index else 0.045
        vol_scale = min(1.0, max_atr_ratio / atr_ratio) if atr_ratio > max_atr_ratio and atr_ratio > 0 else 1.0

        # ADX ve Dual Engine Rejim Tespiti
        # ADX >= 15.0 ve türev pozitifse (veya ADX >= 20.0) -> TRENDING / B-Tarzı Breakout
        is_trending = (latest_adx >= 15.0 and is_adx_rising) or (latest_adx >= 20.0)

        # DIOSC Öncü Sinyali Teyidi (Endekste osilatör daha geniş bantta dalgalanır)
        diosc, diosc_signal, _ = calculate_diosc(hourly_data, adx_period=14, signal_period=9)
        cur_diosc = float(diosc.iloc[-1])
        cur_diosc_sig = float(diosc_signal.iloc[-1])

        # Dinamik ATR Çarpanı
        dynamic_atr_mult = self.get_dynamic_atr_multiplier(latest_adx, is_adx_rising)
        # Brent Petrol Oynaklık Uyumlaması: Jeopolitik şoklar sebebiyle ilk stop 2.5x ATR'ye genişletilir
        if "BRENT" in symbol or "BZ=F" in symbol:
            dynamic_atr_mult = max(2.5, dynamic_atr_mult)

        # Ana Trend Onayı: Günlük SMA(100) & Erken Dip Dönüşü İstisnası
        daily_close = float(daily_data["close"].iloc[-1])
        daily_sma_100 = float(daily_data["close"].rolling(window=100, min_periods=50).mean().iloc[-1])

        is_daily_bull = daily_close > daily_sma_100
        early_bottom_reversal = False
        if not is_daily_bull and len(daily_data) >= 50:
            daily_ema20 = float(calculate_ema(daily_data["close"], period=20).iloc[-1])
            daily_ema50 = float(calculate_ema(daily_data["close"], period=50).iloc[-1])
            if daily_ema20 > daily_ema50 and daily_close > daily_ema20:
                is_daily_bull = True
                early_bottom_reversal = True

        # Saatlik Donchian Kanalları (Shift 1 Lookahead Bias Korumalı)
        don_high, don_low, don_mid = calculate_donchian_channels(hourly_data, period=20)
        prev_don_high = float(don_high.iloc[-1])
        prev_don_low = float(don_low.iloc[-1])

        # Bollinger Bantları ve EMA20 (A-Tarzı İçin)
        bb_upper, bb_mid, bb_lower = calculate_bollinger_bands(hourly_data["close"], period=20, num_std=2.0)
        cur_bb_upper = float(bb_upper.iloc[-1])
        cur_bb_lower = float(bb_lower.iloc[-1])
        ema20_hourly = float(calculate_ema(hourly_data["close"], period=20).iloc[-1])

        # RSI Hesaplama (14 periyot - A-Tarzı Aşırı Alım/Satım Kontrolü)
        rsi_series = calculate_rsi(hourly_data["close"], period=14)
        cur_rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0

        # Hacim Teyidi: Varlık sınıfına göre
        # BIST 30 (F_XU030): 1.15x
        # Sektör Endeksleri (F_XLBNK, F_XUSIN, F_XGMYO): 1.10x
        # Diğer Hisse Long: 1.40x, Short: 1.00x
        if symbol == "F_XU030":
            long_vol_mult = 1.15
        elif is_index:
            long_vol_mult = 1.10
        else:
            long_vol_mult = 1.40
        short_vol_mult = 1.00
        vol_sma20 = float(hourly_data["volume"].rolling(window=20, min_periods=5).mean().iloc[-1])
        current_vol = float(current_bar["volume"])

        # Endeks spot verisinde hacim sıfır ise (Yahoo Finance kısıtı) hacim filtresi onaylanır
        if is_index and (current_vol == 0.0 or vol_sma20 == 0.0):
            is_vol_spike_long = True
            is_vol_spike_short = True
        else:
            is_vol_spike_long = current_vol >= (long_vol_mult * vol_sma20)
            is_vol_spike_short = current_vol >= (short_vol_mult * vol_sma20)

        # =====================================================================
        # LONG GİRİŞ KONTROLÜ (B-Tarzı Breakout & A-Tarzı Destek Tepkisi)
        # =====================================================================
        can_evaluate_long = (dir_bias in (DirectionalBias.ONLY_LONG, DirectionalBias.BI_DIRECTIONAL)) or is_daily_bull

        if can_evaluate_long and is_daily_bull:
            # 1. B-Tarzı Kırılım (Trend rejiminde, Donchian High kırılımı ve hacim teyidi)
            is_b_long = is_trending and (current_price >= prev_don_high) and is_vol_spike_long

            # 2. A-Tarzı Retest / Destek Alımı (EMA20 veya Bollinger Alt Bandı desteği, yeşil boğa dönüş mumu: Close > Open)
            # A-Tarzı Tepki Alımlarına Ek Teyit (Over-Trading Freni):
            # RSI(14) < 35 aşırı satım teyidi VEYA Göreceli Güç (RS > 0, son 5 barda pozitif ayrışma)
            is_green_candle = current_price > bar_open
            is_rsi_oversold = cur_rsi < 35.0
            is_bollinger_touch = float(current_bar["low"]) <= cur_bb_lower
            is_near_ema20 = abs(current_price - ema20_hourly) / max(1.0, ema20_hourly) <= 0.015
            is_at_support = is_bollinger_touch or is_near_ema20

            # Göreceli Güç (RS) Teyidi (Endekse göre pozitif ayrışma)
            rs_positive = (float(hourly_data["close"].iloc[-1]) > float(hourly_data["close"].iloc[-5])) if len(hourly_data) >= 5 else True
            is_a_confirmed = is_rsi_oversold or rs_positive

            # A-Tarzı: Hisse ve emtiada trend içi retest veya yatay piyasada ortalamaya dönüş
            is_a_long = (asset_class != "INDEX") and (not is_trending or is_rsi_oversold) and is_at_support and is_green_candle and is_a_confirmed and (current_vol >= 0.8 * vol_sma20 or is_index)

            if is_b_long or is_a_long:
                # DIOSC Filtresi (B-Tarzında teyit aranır)
                if is_b_long and not is_index and cur_diosc < cur_diosc_sig:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.REJECT_DIOSC_BEARISH,
                        symbol=symbol,
                        target_lots=0,
                        entry_price=current_price,
                        stop_price=0.0,
                        take_profit_target=0.0,
                        expected_rr_ratio=0.0,
                        reason=f"REJECT_DIOSC_BEARISH: DIOSC ({cur_diosc:.1f}) < Sinyal ({cur_diosc_sig:.1f}). Öncü osilatör yükselişi onaylamadı.",
                        metrics={"diosc": cur_diosc, "signal": cur_diosc_sig}
                    )

                initial_stop = round(current_price - (dynamic_atr_mult * hourly_atr), 2)
                risk_dist = current_price - initial_stop

                target_min_rr = 1.5 if is_index else self.MIN_RR_RATIO
                tp_target = round(current_price + (target_min_rr * risk_dist), 2)
                expected_rr = round((tp_target - current_price) / risk_dist, 2) if risk_dist > 0 else 0.0

                if expected_rr < target_min_rr:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.REJECT_RISK_REWARD,
                        symbol=symbol,
                        target_lots=0,
                        entry_price=current_price,
                        stop_price=initial_stop,
                        take_profit_target=tp_target,
                        expected_rr_ratio=expected_rr,
                        reason=f"Risk/Kazanç Barajı Reddi: Beklenen R/K={expected_rr:.2f} < {target_min_rr}",
                        metrics={"dynamic_atr_mult": dynamic_atr_mult}
                    )

                mult_long = eff_multiplier if dir_bias in (DirectionalBias.ONLY_LONG, DirectionalBias.BI_DIRECTIONAL) else (eff_multiplier * 0.75)
                if early_bottom_reversal:
                    mult_long *= 0.5  # Erken dip dönüşü istisnasında 0.5x bütçe
                mult_long *= vol_scale  # Volatilite aşımında yumuşak lot küçültme

                lots, lot_msg = self.calculate_lot_size_with_margin_cap(
                    symbol=symbol,
                    entry_price=current_price,
                    stop_price=initial_stop,
                    portfolio_nav=portfolio_nav,
                    free_margin=free_margin,
                    compass_multiplier=mult_long
                )

                if lots <= 0:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.REJECT_MARGIN,
                        symbol=symbol,
                        target_lots=0,
                        entry_price=current_price,
                        stop_price=initial_stop,
                        take_profit_target=tp_target,
                        expected_rr_ratio=expected_rr,
                        reason=f"Teminat Yetersiz: {lot_msg}",
                        metrics={"dynamic_atr_mult": dynamic_atr_mult}
                    )

                action = ExecutionActionV4.ENTER_LONG if is_b_long else ExecutionActionV4.ENTER_LONG_A_TYPE
                strategy_desc = "B-Tarzı LONG Kırılım" if is_b_long else "A-Tarzı LONG Destek Tepkisi"

                return TechnicalDecisionV4(
                    action=action,
                    symbol=symbol,
                    target_lots=lots,
                    entry_price=current_price,
                    stop_price=initial_stop,
                    take_profit_target=tp_target,
                    expected_rr_ratio=expected_rr,
                    reason=f"{strategy_desc} Onaylandı (Dinamik ATR: {dynamic_atr_mult}x, Volatilite Ölçeği: {vol_scale:.2f}): {lot_msg}",
                    metrics={
                        "strategy_mode": "B_TYPE" if is_b_long else "A_TYPE",
                        "daily_close": daily_close,
                        "daily_sma100": daily_sma_100,
                        "prev_donchian_high": prev_don_high,
                        "volume_ratio": current_vol / max(1.0, vol_sma20),
                        "atr": hourly_atr,
                        "dynamic_atr_mult": dynamic_atr_mult,
                        "compass_multiplier": mult_long,
                        "vol_scale": vol_scale
                    }
                )

        # =====================================================================
        # SHORT GİRİŞ KONTROLÜ (B-Tarzı Breakdown & A-Tarzı Direnç Tepkisi)
        # =====================================================================
        is_daily_bear = daily_close < daily_sma_100
        can_evaluate_short = (dir_bias in (DirectionalBias.ONLY_SHORT, DirectionalBias.BI_DIRECTIONAL)) or is_daily_bear

        if can_evaluate_short and is_daily_bear:
            # 1. B-Tarzı Çöküş / Kırılım (Trend rejiminde, Donchian Low kırılımı ve ortalama hacim teyidi)
            is_b_short = is_trending and (current_price <= prev_don_low) and is_vol_spike_short

            # 2. A-Tarzı Direnç Tepkisi (EMA20 veya Bollinger Üst Bandı direnci, RSI > 65 veya yatay piyasa, kırmızı ayı dönüş mumu: Close < Open)
            is_red_candle = current_price < bar_open
            is_rsi_overbought = cur_rsi > 65.0
            is_bollinger_touch_upper = float(current_bar["high"]) >= cur_bb_upper
            is_near_ema20 = abs(current_price - ema20_hourly) / max(1.0, ema20_hourly) <= 0.015
            is_at_resistance = is_bollinger_touch_upper or is_near_ema20
            is_a_short = (asset_class != "INDEX") and (not is_trending or is_rsi_overbought) and is_at_resistance and is_red_candle and (current_vol >= 0.8 * vol_sma20 or is_index)

            if is_b_short or is_a_short:
                # DIOSC Filtresi (B-Tarzında teyit aranır)
                if is_b_short and not is_index and cur_diosc > cur_diosc_sig:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.REJECT_DIOSC_BEARISH,
                        symbol=symbol,
                        target_lots=0,
                        entry_price=current_price,
                        stop_price=0.0,
                        take_profit_target=0.0,
                        expected_rr_ratio=0.0,
                        reason=f"REJECT_DIOSC_BULLISH: DIOSC ({cur_diosc:.1f}) > Sinyal ({cur_diosc_sig:.1f}). Öncü osilatör düşüşü onaylamadı.",
                        metrics={"diosc": cur_diosc, "signal": cur_diosc_sig}
                    )

                initial_stop = round(current_price + (dynamic_atr_mult * hourly_atr), 2)
                risk_dist = initial_stop - current_price

                target_min_rr = 1.5 if is_index else self.MIN_RR_RATIO
                tp_target = round(current_price - (target_min_rr * risk_dist), 2)
                expected_rr = round((current_price - tp_target) / risk_dist, 2) if risk_dist > 0 else 0.0

                if expected_rr < target_min_rr:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.REJECT_RISK_REWARD,
                        symbol=symbol,
                        target_lots=0,
                        entry_price=current_price,
                        stop_price=initial_stop,
                        take_profit_target=tp_target,
                        expected_rr_ratio=expected_rr,
                        reason=f"Risk/Kazanç Barajı Reddi: Beklenen R/K={expected_rr:.2f} < {target_min_rr}",
                        metrics={"dynamic_atr_mult": dynamic_atr_mult}
                    )

                mult_short = eff_multiplier if dir_bias in (DirectionalBias.ONLY_SHORT, DirectionalBias.BI_DIRECTIONAL) else (eff_multiplier * 0.75)
                mult_short *= vol_scale  # Volatilite aşımında yumuşak lot küçültme

                lots, lot_msg = self.calculate_lot_size_with_margin_cap(
                    symbol=symbol,
                    entry_price=current_price,
                    stop_price=initial_stop,
                    portfolio_nav=portfolio_nav,
                    free_margin=free_margin,
                    compass_multiplier=mult_short
                )

                if lots <= 0:
                    return TechnicalDecisionV4(
                        action=ExecutionActionV4.REJECT_MARGIN,
                        symbol=symbol,
                        target_lots=0,
                        entry_price=current_price,
                        stop_price=initial_stop,
                        take_profit_target=tp_target,
                        expected_rr_ratio=expected_rr,
                        reason=f"Teminat Yetersiz: {lot_msg}",
                        metrics={"dynamic_atr_mult": dynamic_atr_mult}
                    )

                action = ExecutionActionV4.ENTER_SHORT if is_b_short else ExecutionActionV4.ENTER_SHORT_A_TYPE
                strategy_desc = "B-Tarzı SHORT Kırılım" if is_b_short else "A-Tarzı SHORT Direnç Tepkisi"

                return TechnicalDecisionV4(
                    action=action,
                    symbol=symbol,
                    target_lots=lots,
                    entry_price=current_price,
                    stop_price=initial_stop,
                    take_profit_target=tp_target,
                    expected_rr_ratio=expected_rr,
                    reason=f"{strategy_desc} Onaylandı (Dinamik ATR: {dynamic_atr_mult}x, Volatilite Ölçeği: {vol_scale:.2f}): {lot_msg}",
                    metrics={
                        "strategy_mode": "B_TYPE" if is_b_short else "A_TYPE",
                        "daily_close": daily_close,
                        "daily_sma100": daily_sma_100,
                        "prev_donchian_low": prev_don_low,
                        "volume_ratio": current_vol / max(1.0, vol_sma20),
                        "atr": hourly_atr,
                        "dynamic_atr_mult": dynamic_atr_mult,
                        "compass_multiplier": mult_short,
                        "vol_scale": vol_scale
                    }
                )

        # [KURAL]: Testere Kalkanı (ADX < 20.0)
        # Ali Perşembe Doktrini: ADX < 20 testere piyasasını temsil eder.
        # Esneklik İstisnası: Yalnızca hacimli Donchian kırılımı ve ΔADX > 0 varsa veya A-tarzı tepki varsa işlem açılır.
        # Giriş şartı oluşmamışsa ve ADX < 20 ise doğrudan Testere Kalkanı ile veto edilir.
        if latest_adx < 20.0:
            return TechnicalDecisionV4(
                action=ExecutionActionV4.REJECT_TESTERE_ADX_DUSUK,
                symbol=symbol,
                target_lots=0,
                entry_price=current_price,
                stop_price=0.0,
                take_profit_target=0.0,
                expected_rr_ratio=0.0,
                reason=f"REJECT_TESTERE_ADX_DUSUK: ADX(14) = {latest_adx:.1f} < 20.0. Testere Kalkanı devrede, işlem veto edildi.",
                metrics={"adx": latest_adx}
            )

        return TechnicalDecisionV4(
            action=ExecutionActionV4.HOLD,
            symbol=symbol,
            target_lots=0,
            entry_price=current_price,
            stop_price=0.0,
            take_profit_target=0.0,
            expected_rr_ratio=0.0,
            reason="Giriş şartları oluşmadı. Beklemede kalın.",
            metrics={}
        )


class TechnicalExecutionerV4:
    """
    VİOP Teknik Karar Motoru (v4.0 - Ali Perşembe Doktrini & Dual Engine).
    Hafif/Doğrudan Sözlük (Dict) Arayüzü:
    evaluate(symbol, bar_data, daily_data, position_state) -> dict
    """
    def __init__(self, config=None):
        self.config = config
        self.MIN_ADX_BREAKOUT = 15.0  # Esnetilmiş ADX eşiği
        self.NO_TRADE_FX = ["F_USDTRY", "F_EURTRY", "F_GBPTRY", "F_DXY", "F_EURUSD"] # FX Kısıtlı Listesi

    def evaluate(self, symbol: str, bar_data: dict, daily_data: dict, position_state=None) -> dict:
        close_p = bar_data['close'][-1]
        open_p = bar_data['open'][-1]
        atr14 = bar_data['atr14'][-1]
        adx14 = bar_data['adx14'][-1]
        adx_slope = adx14 - bar_data['adx14'][-2] if len(bar_data['adx14']) >= 2 else 0.0
        
        # 1. DÖVİZ VE DXY ÇIPLAK BREAKOUT ENGELİ (REJECT_FX_CARRY_ONLY)
        if symbol in self.NO_TRADE_FX or any(fx in symbol for fx in ("USDTRY", "EURTRY", "GBPTRY", "DXY", "EURUSD")):
            return {"action": ExecutionActionV4.REJECT_FX_CARRY_ONLY, "reason": "FX Carry-Only Mode"}

        # 2. VOLATİLİTE ÖLÇEKLEME (vol_scale)
        max_atr_ratio = 0.015 if "XU030" in symbol else 0.045
        current_atr_ratio = atr14 / close_p if close_p > 0 else 0.0
        vol_scale = 1.0
        if current_atr_ratio > max_atr_ratio and current_atr_ratio > 0:
            vol_scale = max_atr_ratio / current_atr_ratio  # Risk korunarak lot büzüştürülür

        # 3. PİYASA REJİMİ TESPİTİ
        is_trending = (adx14 >= self.MIN_ADX_BREAKOUT) and (adx_slope > 0)
        
        # Üst Vade (Daily) Trend Yönü
        daily_close = daily_data['close'][-1]
        daily_sma100 = daily_data['sma100'][-1]
        upper_trend_up = daily_close > daily_sma100
        upper_trend_down = daily_close < daily_sma100

        has_no_pos = True
        if position_state is not None:
            if hasattr(position_state, "has_no_position"):
                has_no_pos = position_state.has_no_position()
            elif hasattr(position_state, "is_active"):
                has_no_pos = not position_state.is_active

        # --- LONG SİNYAL MANTIĞI ---
        if upper_trend_up and has_no_pos:
            # B-Tarzı Long Kırılım
            vol_mult = 1.15 if "XU030" in symbol else 1.40
            vol_val = bar_data['volume'][-1]
            vol_sma = bar_data.get('vol_sma20', [vol_val])[-1]
            is_vol_spike = vol_val >= (vol_mult * vol_sma) if vol_sma > 0 else True
            don_high_ref = bar_data['donchian_high'][-2] if len(bar_data['donchian_high']) >= 2 else bar_data['donchian_high'][-1]
            is_donchian_break = close_p >= don_high_ref
            
            aps = bar_data.get('total_aps')
            aps_increasing = (aps[-1] > aps[-2]) if aps and len(aps) >= 2 else True

            if is_trending and is_donchian_break and is_vol_spike and aps_increasing:
                return {
                    "action": ExecutionActionV4.ENTER_LONG_B_TYPE,
                    "entry_price": close_p,
                    "stop_price": close_p - (2.0 * atr14),
                    "vol_scale": vol_scale
                }

            # A-Tarzı Long Tepki (Mean-Reversion)
            rsi_val = bar_data.get('rsi14', [50.0])[-1]
            is_rsi_oversold = rsi_val < 35.0
            boll_lower = bar_data.get('bollinger_lower', [close_p])[-1]
            low_p = bar_data.get('low', [close_p])[-1]
            is_bollinger_touch = low_p <= boll_lower
            is_green_candle = close_p > open_p

            if (not is_trending or is_rsi_oversold) and is_bollinger_touch and is_green_candle:
                return {
                    "action": ExecutionActionV4.ENTER_LONG_A_TYPE,
                    "entry_price": close_p,
                    "stop_price": close_p - (1.5 * atr14),
                    "vol_scale": vol_scale * 0.75 # A-Tarzı bütçe %75
                }

        # --- SHORT SİNYAL MANTIĞI ---
        elif upper_trend_down and has_no_pos:
            # B-Tarzı Short Kırılım (Alıcısız Düşüş: Hacim >= 1.0x Yeterli)
            vol_val = bar_data['volume'][-1]
            vol_sma = bar_data.get('vol_sma20', [vol_val])[-1]
            is_vol_normal = vol_val >= (1.0 * vol_sma) if vol_sma > 0 else True
            don_low_ref = bar_data['donchian_low'][-2] if len(bar_data['donchian_low']) >= 2 else bar_data['donchian_low'][-1]
            is_donchian_break_short = close_p <= don_low_ref

            aps = bar_data.get('total_aps')
            aps_increasing = (aps[-1] > aps[-2]) if aps and len(aps) >= 2 else True

            if is_trending and is_donchian_break_short and is_vol_normal and aps_increasing:
                return {
                    "action": ExecutionActionV4.ENTER_SHORT_B_TYPE,
                    "entry_price": close_p,
                    "stop_price": close_p + (2.0 * atr14),
                    "vol_scale": vol_scale
                }

            # A-Tarzı Short Tepki
            rsi_val = bar_data.get('rsi14', [50.0])[-1]
            is_rsi_overbought = rsi_val > 65.0
            boll_upper = bar_data.get('bollinger_upper', [close_p])[-1]
            high_p = bar_data.get('high', [close_p])[-1]
            is_bollinger_touch_upper = high_p >= boll_upper
            is_red_candle = close_p < open_p

            if (not is_trending or is_rsi_overbought) and is_bollinger_touch_upper and is_red_candle:
                return {
                    "action": ExecutionActionV4.ENTER_SHORT_A_TYPE,
                    "entry_price": close_p,
                    "stop_price": close_p + (1.5 * atr14),
                    "vol_scale": vol_scale * 0.75
                }

        return {"action": ExecutionActionV4.HOLD}

