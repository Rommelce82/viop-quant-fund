"""
VİOP Otomatik Vade Sonu Geçişi ve Calendar Spread Kontrol Katmanı
(src/strategy/roll_over_manager.py).

Ali Perşembe Doktrini:
1. Roll-Over Takvimi: Çift ayların (Şubat, Nisan, Haziran, Ağustos, Ekim, Aralık)
   son işlem gününe 3 iş günü kala yakın vadeden uzak vadeye geçiş tetiklenir.
2. Calendar Spread Kontrolü: İki sözleşme arasındaki fiyat makasının
   teorik faiz taşıma maliyetine (Fair Spread) uygunluğu denetlenir:
   Spread = Uzak Vade Fiyatı - Yakın Vade Fiyatı
   Fair Spread = Yakın Vade * (TLREF * delta_t / 365)
   Sapma <= %0.50 ise geçiş onaylanır, aşırı sapmada arbitraj / bekleme uygulanır.
"""

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RollOverDecision:
    should_roll: bool
    near_symbol: str
    far_symbol: str
    days_to_expiry: int
    calendar_spread: float
    fair_spread: float
    spread_deviation_pct: float
    is_spread_fair: bool
    action: str  # 'ROLL_NOW', 'WAIT_FOR_FAIR_SPREAD', 'NO_ROLL'
    reason: str


class ViopRollOverManager:
    """
    VİOP Sözleşmeleri İçin Otomatik Vade Sonu Geçiş ve Calendar Spread Yöneticisi.
    """

    EXPIRY_MONTHS = {2, 4, 6, 8, 10, 12}  # Çift Aylar
    DAYS_BEFORE_EXPIRY_TRIGGER = 3        # Vade sonuna 3 iş günü kala tetiklenir
    MAX_SPREAD_DEVIATION_PCT = 0.005      # Maksimum %0.50 spread sapma toleransı

    @staticmethod
    def get_last_business_day_of_month(year: int, month: int) -> date:
        """Ayın son iş gününü (Pazartesi-Cuma) bulur."""
        if month == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month + 1, 1)
        last_day = next_month - timedelta(days=1)
        # Hafta sonu ise geriye çek
        while last_day.weekday() >= 5:  # 5=Cumartesi, 6=Pazar
            last_day -= timedelta(days=1)
        return last_day

    @classmethod
    def get_days_to_expiry(cls, current_dt: datetime) -> Tuple[int, date, bool]:
        """
        Mevcut tarihin aktif vade sonuna kaç iş günü kaldığını hesaplar.
        Returns: (kalan_is_gunu, son_is_gunu, is_expiry_month)
        """
        cur_date = current_dt.date() if isinstance(current_dt, datetime) else current_dt
        year = cur_date.year
        month = cur_date.month

        # Eğer çift ay değilse, bir sonraki çift aya kadar vade sonu değildir
        if month not in cls.EXPIRY_MONTHS:
            # En yakın sonraki çift ayı bul
            target_month = month + 1
            target_year = year
            expiry_date = cls.get_last_business_day_of_month(target_year, target_month)
            days = (expiry_date - cur_date).days
            return days, expiry_date, False

        expiry_date = cls.get_last_business_day_of_month(year, month)
        if cur_date > expiry_date:
            # Bu ayın vadesi dolmuş, 2 ay sonrasına bak
            target_month = (month + 2) if month <= 10 else 2
            target_year = year if month <= 10 else (year + 1)
            expiry_date = cls.get_last_business_day_of_month(target_year, target_month)
            days = (expiry_date - cur_date).days
            return days, expiry_date, False

        # İş günü hesabı
        cur_cursor = cur_date
        business_days = 0
        while cur_cursor < expiry_date:
            cur_cursor += timedelta(days=1)
            if cur_cursor.weekday() < 5:
                business_days += 1

        return business_days, expiry_date, True

    @classmethod
    def evaluate_rollover(
        cls,
        symbol: str,
        current_dt: datetime,
        near_price: float,
        far_price: Optional[float] = None,
        tlref_rate: float = 0.48
    ) -> RollOverDecision:
        """
        Vade geçişi gerekip gerekmediğini ve Calendar Spread makasının adilliğini değerlendirir.
        """
        b_days, expiry_d, is_expiry_m = cls.get_days_to_expiry(current_dt)

        if not is_expiry_m or b_days > cls.DAYS_BEFORE_EXPIRY_TRIGGER:
            return RollOverDecision(
                should_roll=False,
                near_symbol=symbol,
                far_symbol="",
                days_to_expiry=b_days,
                calendar_spread=0.0,
                fair_spread=0.0,
                spread_deviation_pct=0.0,
                is_spread_fair=True,
                action="NO_ROLL",
                reason=f"Vade sonuna {b_days} iş günü var. Geçiş penceresi henüz açılmadı (Eşik: <= {cls.DAYS_BEFORE_EXPIRY_TRIGGER} gün)."
            )

        # Uzak vade fiyatı verilmemişse teorik faizle hesapla
        dt_years = 60.0 / 365.0  # 2 ay (60 gün)
        fair_spread = round(near_price * (tlref_rate * dt_years), 2)
        actual_far_price = far_price if (far_price is not None and far_price > 0) else (near_price + fair_spread)
        calendar_spread = round(actual_far_price - near_price, 2)

        # Spread sapma yüzdesi
        spread_dev = abs(calendar_spread - fair_spread) / near_price if near_price > 0 else 0.0
        is_fair = spread_dev <= cls.MAX_SPREAD_DEVIATION_PCT

        if is_fair:
            return RollOverDecision(
                should_roll=True,
                near_symbol=symbol,
                far_symbol=f"{symbol}_FAR",
                days_to_expiry=b_days,
                calendar_spread=calendar_spread,
                fair_spread=fair_spread,
                spread_deviation_pct=spread_dev,
                is_spread_fair=True,
                action="ROLL_NOW",
                reason=f"Vade sonuna {b_days} iş günü kaldı. Calendar Spread ({calendar_spread:.2f} TL) teorik faize ({fair_spread:.2f} TL) uygun. Otomatik Roll-Over icra edildi."
            )
        else:
            return RollOverDecision(
                should_roll=False,
                near_symbol=symbol,
                far_symbol=f"{symbol}_FAR",
                days_to_expiry=b_days,
                calendar_spread=calendar_spread,
                fair_spread=fair_spread,
                spread_deviation_pct=spread_dev,
                is_spread_fair=False,
                action="WAIT_FOR_FAIR_SPREAD",
                reason=f"Calendar Spread sapması yüksek (%{spread_dev*100:.2f} > %{cls.MAX_SPREAD_DEVIATION_PCT*100:.2f}). Makasın normalleşmesi bekleniyor."
            )
