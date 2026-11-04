"""
Pozisyon Durum Yönetimi ve İcra Modülü (Position State & PositionManagerV4).

Ali Perşembe Doktrini (v4.0):
- Tapi (Breakeven) Retest Marjı (+1.0R kârda Entry +- 0.5x ATR).
- %33 Scale-Out (+2.0R kârda 1/3 pozisyon kapatma).
- Chandelier Trailing Stop (2.5x ATR).
- Kesin Çıkış: Trend Reversal (SMA20 altı/üstü 2 ardışık bar veya Günlük SMA100 kırılımı).
- Zaman Stopu (30 bar hareketsizlik, kârdaysa dondurma).
"""

from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import Any, Dict, Optional


@dataclass
class PositionState:
    """
    Tekil VİOP Pozisyon Durum Nesnesi.

    Attributes:
        symbol: Sözleşme sembolü (Örn: F_THYAO, F_XU030).
        entry_price: Pozisyona giriş fiyatı.
        initial_stop: İlk zarar durdur seviyesi.
        trailing_stop: Güncel iz süren stop seviyesi.
        lots: Mevcut açık kontrat adedi (Pozitif = Long, Negatif = Short).
        bars_held: Pozisyon açıldıktan sonra geçen bar sayısı (Saatlik TF).
        scaled_out: Kâr realizasyonu yapıldı mı?
        entry_time: Pozisyona giriş zaman damgası.
        r_unit_price: 1R risk birimi (entry_price - initial_stop).
        max_r_seen: Pozisyon boyunca görülen en yüksek R katsayısı.
        is_breakeven_activated: Tapi (retest marjlı) başabaş stopu devreye girdi mi?
        has_scaled_out_33: +2.0R'de %33 scale-out yapıldı mı?
    """
    symbol: str
    entry_price: float
    initial_stop: float
    trailing_stop: float
    lots: int
    bars_held: int = 0
    scaled_out: bool = False
    entry_time: Optional[datetime] = None
    r_unit_price: float = 0.0
    max_r_seen: float = 0.0
    is_breakeven_activated: bool = False
    has_scaled_out_33: bool = False
    is_pyramided: bool = False
    pyramid_lots: int = 0
    entry_commission_paid: float = 0.0

    def __post_init__(self) -> None:
        if self.r_unit_price == 0.0 and self.entry_price > 0 and self.initial_stop > 0:
            self.r_unit_price = abs(self.entry_price - self.initial_stop)

    def can_pyramid(self, current_r: float) -> bool:
        """
        Bedava Piramitleme Şartı (Ali Perşembe Doktrini):
        Pozisyon >= +2.0R kârda, stop maliyetin üzerinde/breakeven'da (risk sıfır)
        ve daha önce piramitleme yapılmamış olmalı.
        """
        return (not self.is_pyramided) and (current_r >= 2.0) and self.is_breakeven_activated

    def add_pyramid(self, additional_lots: int) -> int:
        """Kârlı pozisyona bedava piramit lot ekler."""
        if self.lots > 0:
            self.lots += additional_lots
        elif self.lots < 0:
            self.lots -= additional_lots
        self.pyramid_lots += additional_lots
        self.is_pyramided = True
        return abs(self.lots)

    @property
    def is_active(self) -> bool:
        """Pozisyonun açık olup olmadığını döner."""
        return self.lots != 0

    @property
    def is_long(self) -> bool:
        """Pozisyonun Long olup olmadığını döner."""
        return self.lots > 0

    @property
    def is_short(self) -> bool:
        """Pozisyonun Short olup olmadığını döner."""
        return self.lots < 0

    @property
    def initial_stop_price(self) -> float:
        return self.initial_stop

    @initial_stop_price.setter
    def initial_stop_price(self, val: float):
        self.initial_stop = val

    @property
    def stop_price(self) -> float:
        return self.trailing_stop

    @stop_price.setter
    def stop_price(self, val: float):
        self.trailing_stop = val

    @property
    def current_lots(self) -> int:
        return abs(self.lots)

    @current_lots.setter
    def current_lots(self, val: int):
        if self.lots > 0:
            self.lots = val
        elif self.lots < 0:
            self.lots = -val
        else:
            self.lots = val

    def has_no_position(self) -> bool:
        """Pozisyonun kapalı veya sıfır olduğunu döner."""
        return self.lots == 0

    def increment_bars_held(self) -> int:
        """Geçen bar sayısını 1 artırır."""
        self.bars_held += 1
        return self.bars_held

    def get_current_r_multiple(self, current_price: float) -> float:
        """Mevcut kâr/zararı R katsayısı cinsinden hesaplar."""
        if self.r_unit_price <= 0.0:
            return 0.0
        if self.lots > 0:
            return (current_price - self.entry_price) / self.r_unit_price
        else:
            return (self.entry_price - current_price) / self.r_unit_price


class PositionManagerV4:
    """
    Ali Perşembe Doktrini Pozisyon ve Çıkış Yöneticisi (v4.0).
    """

    def update_and_evaluate_exit(
        self,
        position: PositionState,
        current_bar: Dict[str, Any],
        daily_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Bar bar açık pozisyonun kârını, Tapi retest marjını, %33 scale-out'u,
        Chandelier iz süren stopunu ve Trend Reversal kesin çıkışını değerlendirir.
        """
        close_p = float(current_bar['close'])
        high_p = float(current_bar.get('high', close_p))
        low_p = float(current_bar.get('low', close_p))
        atr14 = float(current_bar.get('atr14', 1.0))

        position.bars_held += 1
        r_distance = abs(position.entry_price - position.initial_stop_price)

        # --- LONG POZİSYON YÖNETİMİ ---
        if position.is_long:
            current_r = (close_p - position.entry_price) / r_distance if r_distance > 0 else 0.0
            position.max_r_seen = max(position.max_r_seen, current_r)

            # 1. TAPI (BREAKEVEN) RETEST MARJI (1.0R Kârda)
            if position.max_r_seen >= 1.0 and not position.is_breakeven_activated:
                position.is_breakeven_activated = True
                # Tam maliyete değil, Retest Marjı: Entry - 0.5x ATR
                position.stop_price = max(position.stop_price, round(position.entry_price - (0.5 * atr14), 2))

            # 2. KADEMELİ KÂR SATIŞI (%33 Scale-Out at +2.0R)
            if current_r >= 2.0 and not position.has_scaled_out_33 and position.current_lots > 1:
                position.has_scaled_out_33 = True
                lots_to_close = math.ceil(position.current_lots * 0.33)
                position.current_lots -= lots_to_close
                return {"action": "SCALE_OUT_33", "closed_lots": lots_to_close, "remaining_lots": position.current_lots}

            # 3. CHANDELIER İZ SÜREN STOP (Highest High - 2.5x ATR)
            highest_ref = float(current_bar.get('highest_high_20', high_p))
            chandelier_stop = round(highest_ref - (2.5 * atr14), 2)
            position.stop_price = max(position.stop_price, chandelier_stop)

            # 4. KESİN ÇIKIŞ: TREND REVERSAL EXIT (SMA20 Altı 2 Kapanış veya Günlük SMA100 Çöküşü)
            sma20_cur = float(current_bar.get('sma20', 0.0))
            prev_close = float(current_bar.get('prev_close', close_p))
            prev_sma20 = float(current_bar.get('prev_sma20', sma20_cur))
            sma20_breakout_exit = (sma20_cur > 0 and close_p < sma20_cur and prev_close < prev_sma20)

            daily_close = daily_data['close'][-1] if isinstance(daily_data.get('close'), (list, tuple)) else daily_data.get('close', close_p)
            daily_sma100 = daily_data['sma100'][-1] if isinstance(daily_data.get('sma100'), (list, tuple)) else daily_data.get('sma100', daily_close)
            daily_trend_flip = float(daily_close) < float(daily_sma100)

            if sma20_breakout_exit or daily_trend_flip:
                reason = "Günlük Close < SMA100" if daily_trend_flip else "SMA20 altı 2 ardışık bar"
                return {"action": "CLOSE_TREND_REVERSAL", "lots": position.current_lots, "reason": reason}

            # 5. ZAMAN STOPU (30 Bar ve Zarardaysa)
            if position.bars_held >= 30 and current_r <= 0.0:
                return {"action": "CLOSE_TIME_STOP", "lots": position.current_lots, "reason": "30 bar kârsızlık"}

            # Stop Kontrolü
            if low_p <= position.stop_price:
                return {"action": "CLOSE_STOP_LOSS", "lots": position.current_lots, "stop_price": position.stop_price}

        # --- SHORT POZİSYON YÖNETİMİ ---
        elif position.is_short:
            current_r = (position.entry_price - close_p) / r_distance if r_distance > 0 else 0.0
            position.max_r_seen = max(position.max_r_seen, current_r)

            # 1. TAPI RETEST MARJI (Short için Entry + 0.5x ATR)
            if position.max_r_seen >= 1.0 and not position.is_breakeven_activated:
                position.is_breakeven_activated = True
                position.stop_price = min(position.stop_price, round(position.entry_price + (0.5 * atr14), 2))

            # 2. KADEMELİ KÂR SATIŞI (%33 Scale-Out at +2.0R)
            if current_r >= 2.0 and not position.has_scaled_out_33 and position.current_lots > 1:
                position.has_scaled_out_33 = True
                lots_to_close = math.ceil(position.current_lots * 0.33)
                position.current_lots -= lots_to_close
                return {"action": "SCALE_OUT_33", "closed_lots": lots_to_close, "remaining_lots": position.current_lots}

            # 3. CHANDELIER İZ SÜREN STOP (Lowest Low + 2.5x ATR)
            lowest_ref = float(current_bar.get('lowest_low_20', low_p))
            chandelier_stop_short = round(lowest_ref + (2.5 * atr14), 2)
            position.stop_price = min(position.stop_price, chandelier_stop_short)

            # 4. KESİN ÇIKIŞ: TREND REVERSAL EXIT (SMA20 Üstü 2 Kapanış veya Günlük SMA100 Yukarısı)
            sma20_cur = float(current_bar.get('sma20', 0.0))
            prev_close = float(current_bar.get('prev_close', close_p))
            prev_sma20 = float(current_bar.get('prev_sma20', sma20_cur))
            sma20_breakout_exit_short = (sma20_cur > 0 and close_p > sma20_cur and prev_close > prev_sma20)

            daily_close = daily_data['close'][-1] if isinstance(daily_data.get('close'), (list, tuple)) else daily_data.get('close', close_p)
            daily_sma100 = daily_data['sma100'][-1] if isinstance(daily_data.get('sma100'), (list, tuple)) else daily_data.get('sma100', daily_close)
            daily_trend_flip_short = float(daily_close) > float(daily_sma100)

            if sma20_breakout_exit_short or daily_trend_flip_short:
                reason = "Günlük Close > SMA100" if daily_trend_flip_short else "SMA20 üstü 2 ardışık bar"
                return {"action": "CLOSE_TREND_REVERSAL", "lots": position.current_lots, "reason": reason}

            # 5. ZAMAN STOPU (30 Bar ve Zarardaysa)
            if position.bars_held >= 30 and current_r <= 0.0:
                return {"action": "CLOSE_TIME_STOP", "lots": position.current_lots, "reason": "30 bar kârsızlık"}

            # Stop Kontrolü
            if high_p >= position.stop_price:
                return {"action": "CLOSE_STOP_LOSS", "lots": position.current_lots, "stop_price": position.stop_price}

        return {"action": "HOLD"}
