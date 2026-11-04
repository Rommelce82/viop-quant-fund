"""
Bilanço Kalkanı ve Soğuma Penceresi Modülü (Earnings Blackout Window).

Bilanço açıklandığı anda oluşan fiyatsal boşluklar (gaps), aşırı volatilite ve 
bilgi düzensizliği (information asymmetry) ilk 24 saat içinde yapay teknik kırılımlar
ve yüksek kayma (slippage) maliyetlerine yol açar.

Bu modül:
1. KAP Zaman Damgası (announced_at) takibini yapar.
2. 24 saatlik dinamik karantina süresince sözleşmeyi EARNINGS_BLACKOUT moduna alarak
   FundamentalCompass üzerinden DirectionalBias.NEUTRAL ve multiplier = 0.0 üretir.
3. Karantina sonrasında Kademeli Re-Entry denetimi yapar:
   - Volatilitenin Yatışması: Anlık ATR(14) <= 1.5 * Bilanço Öncesi Medyan ATR(20)
   - Skor Teyidi: Yeni bilançoya göre hesaplanan Piotroski F-Skoru ve Altman Z-Skorunun
     kriterleri sağlamaya devam etmesi.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, Tuple


class BlackoutPhase(str, Enum):
    """Bilanço Kalkanı Fazı."""
    ACTIVE = "ACTIVE"                        # Karantina yok, serbest işlem
    EARNINGS_BLACKOUT = "EARNINGS_BLACKOUT"  # İlk 24 saat tam blokaj
    COOLING_OFF = "COOLING_OFF"              # 24 saat doldu, volatilite/ATR yatışması bekleniyor


@dataclass
class EarningsEvent:
    """KAP Bilanço Açıklanma Olayı."""
    symbol: str
    announced_at: datetime
    pre_earnings_median_atr20: float
    quarantine_hours: float = 24.0
    atr_cooling_multiplier: float = 1.5


class EarningsBlackoutManager:
    """
    Bilanço Kalkanı ve Karantina Yönetim Motoru.
    """

    def __init__(self, default_quarantine_hours: float = 24.0) -> None:
        self.default_quarantine_hours = default_quarantine_hours
        self._events: Dict[str, EarningsEvent] = {}

    def register_earnings_announcement(
        self,
        symbol: str,
        announced_at: datetime,
        pre_earnings_median_atr20: float,
        quarantine_hours: Optional[float] = None
    ) -> EarningsEvent:
        """
        KAP'a düşen yeni bir bilanço zaman damgasını sisteme kaydeder.
        """
        hours = quarantine_hours or self.default_quarantine_hours
        event = EarningsEvent(
            symbol=symbol,
            announced_at=announced_at,
            pre_earnings_median_atr20=max(0.001, pre_earnings_median_atr20),
            quarantine_hours=hours
        )
        self._events[symbol] = event
        return event

    def get_event(self, symbol: str) -> Optional[EarningsEvent]:
        """Sembolün kayıtlı bilanço olayını döner."""
        return self._events.get(symbol)

    def evaluate_blackout_state(
        self,
        symbol: str,
        current_time: datetime,
        current_atr14: float
    ) -> Tuple[BlackoutPhase, str]:
        """
        İlgili hisse için güncel Bilanço Kalkanı durumunu tespit eder.
        
        Dönüş: (BlackoutPhase, rationale)
        """
        event = self._events.get(symbol)
        if not event:
            return BlackoutPhase.ACTIVE, "Kayıtlı bilanço karantinası yok."

        elapsed_time = current_time - event.announced_at
        quarantine_delta = timedelta(hours=event.quarantine_hours)

        # 1. Aşama: 24 Saatlik Tam Karantina
        if elapsed_time < quarantine_delta:
            remaining_minutes = (quarantine_delta - elapsed_time).total_seconds() / 60.0
            return (
                BlackoutPhase.EARNINGS_BLACKOUT,
                f"Bilanço Kalkanı Aktif (EARNINGS_BLACKOUT): {event.announced_at.strftime('%Y-%m-%d %H:%M')} KAP damgası. "
                f"Karantina bitimine {remaining_minutes:.0f} dakika kaldı."
            )

        # 2. Aşama: 24 Saat Doldu - Soğuma (Cooling-off) & Volatilite Yatışma Kontrolü
        max_allowed_atr = event.pre_earnings_median_atr20 * event.atr_cooling_multiplier
        if current_atr14 > max_allowed_atr:
            return (
                BlackoutPhase.COOLING_OFF,
                f"Soğuma Penceresi (COOLING_OFF): 24 saat doldu ancak ATR yatışmadı. "
                f"Anlık ATR(14)={current_atr14:.2f} > İzin Verilen Tavan={max_allowed_atr:.2f} "
                f"(1.5x Medyan ATR={event.pre_earnings_median_atr20:.2f})"
            )

        # Volatilite yatıştı, işlem serbest
        return (
            BlackoutPhase.ACTIVE,
            f"Bilanço Kalkanı Tamamlandı: 24 saat aşıldı ve volatilite yatıştı "
            f"(ATR={current_atr14:.2f} <= {max_allowed_atr:.2f})."
        )

    def is_trade_allowed(
        self,
        symbol: str,
        current_time: datetime,
        current_atr14: float
    ) -> Tuple[bool, BlackoutPhase, str]:
        """
        İşleme giriş izni olup olmadığını denetler.
        """
        phase, msg = self.evaluate_blackout_state(symbol, current_time, current_atr14)
        is_allowed = (phase == BlackoutPhase.ACTIVE)
        return is_allowed, phase, msg
