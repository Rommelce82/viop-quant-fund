"""
VİOP Vade Döngüsü ve Rollover Zamanlayıcısı (Rollover Scheduler).

Anayasa Kademe 5 Kurallarına Göre:
- Fiziki Teslimat (Physical Delivery) (Örn: Pay Vadeli Sözleşmeleri - F_THYAO, F_GARAN, F_AKBNK):
  * Vadeye 5 iş günü kala kademeli rollover (taşınma) başlar.
  * Vadeye 2 iş günü kala saat 17:00'da açık kalan pozisyonlar için KESİN VE ZORUNLU KAPATMA
    (MANDATORY_CLOSE) sinyali üretilir (Fiziki hisse teslimatı ve temerrüt riskini engellemek için).
- Nakdi Uzlaşma (Cash Settlement) (Örn: Endeks Vadeli Sözleşmesi - F_XU030):
  * Vadeye 3 iş günü kala rollover süreci başlar.
  * Vade sonu günü saat 12:00, 15:00 ve en geç 16:00'da pozisyonlar piyasa emriyle kapatılır.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
import logging
from typing import Callable, Dict, List, Optional, Tuple
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)


class SettlementType(str, Enum):
    """VİOP Uzlaşma Yöntemi."""
    PHYSICAL = "PHYSICAL"      # Fiziki Teslimat (Pay VİOP Kontratları)
    CASH = "CASH"              # Nakdi Uzlaşma (Endeks VİOP Kontratları - F_XU030)


class RolloverAction(str, Enum):
    """Zamanlayıcı Eylem Tipi."""
    START_ROLLOVER = "START_ROLLOVER"          # Yeni vadeye geçiş başlat
    MANDATORY_CLOSE = "MANDATORY_CLOSE"        # Kesin piyasa emriyle kapat
    MONITOR_ONLY = "MONITOR_ONLY"              # Güvenli vade aralığı


@dataclass(frozen=True)
class ContractExpiryInfo:
    """
    Sözleşme Vade ve Teslimat Bilgisi.
    """
    symbol: str
    settlement_type: SettlementType
    expiry_date: datetime                      # Vade sonu işlem günü (Genellikle ayın son iş günü)


class ViopRolloverScheduler:
    """
    VİOP Vade Sonu ve Pozisyon Taşıma Zamanlayıcı Motoru.
    """

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self._action_callbacks: List[Callable[[str, RolloverAction, str], None]] = []
        self._contracts: Dict[str, ContractExpiryInfo] = {}

    def register_contract(self, info: ContractExpiryInfo) -> None:
        """İzlenecek VİOP sözleşmesini kaydeder."""
        self._contracts[info.symbol] = info

    def on_action(self, callback: Callable[[str, RolloverAction, str], None]) -> None:
        """Zorunlu kapatma veya rollover eylemleri için callback dinleyici ekler."""
        self._action_callbacks.append(callback)

    def _trigger_action(self, symbol: str, action: RolloverAction, reason: str) -> None:
        """Kayıtlı dinleyicilere sinyal dağıtır."""
        logger.warning("[ROLLOVER ALARM] %s -> %s | Sebep: %s", symbol, action.value, reason)
        for cb in self._action_callbacks:
            try:
                cb(symbol, action, reason)
            except Exception as exc:
                logger.error("Callback çalıştırma hatası: %s", exc)

    def evaluate_contract_status(
        self,
        symbol: str,
        current_time: datetime
    ) -> Tuple[RolloverAction, str]:
        """
        Belirtilen zaman damgasında sözleşmenin vade durumunu ve yapılması gereken işlemi denetler.
        """
        info = self._contracts.get(symbol)
        if not info:
            return RolloverAction.MONITOR_ONLY, "Sözleşme kayıtlı değil."

        expiry_dt = info.expiry_date
        # Gün farkı hesabı (Saatleri sıfırlayarak sadece takvim günü)
        days_to_expiry = (expiry_dt.date() - current_time.date()).days

        # ---------------------------------------------------------------------
        # KURAL 1: FİZİKİ TESLİMATLI SÖZLEŞMELER (PAY VİOP)
        # ---------------------------------------------------------------------
        if info.settlement_type == SettlementType.PHYSICAL:
            # Vadeye 2 gün veya daha az kaldıysa
            if days_to_expiry < 2:
                return (
                    RolloverAction.MANDATORY_CLOSE,
                    f"Fiziki Teslimat Kuralı: Vadeye {days_to_expiry} gün kaldı! Fiziki hisse teslimatı riski nedeniyle ZORUNLU KAPATMA."
                )
            elif days_to_expiry == 2:
                # Vadeye 2 gün kala saat 17:00'dan sonra ZORUNLU KAPATMA
                if current_time.time() >= time(17, 0):
                    return (
                        RolloverAction.MANDATORY_CLOSE,
                        "Fiziki Teslimat Kuralı: Vadeye 2 gün kala saat 17:00 aşıldı! ZORUNLU KAPATMA."
                    )
                else:
                    return (
                        RolloverAction.START_ROLLOVER,
                        "Fiziki Teslimat Kuralı: Vadeye 2 gün kaldı, saat 17:00 öncesi pozisyonu yeni vadeye taşıyın."
                    )
            elif days_to_expiry <= 5:
                return (
                    RolloverAction.START_ROLLOVER,
                    f"Fiziki Teslimat Kuralı: Vadeye {days_to_expiry} gün kaldı, kademeli rollover aktif."
                )

        # ---------------------------------------------------------------------
        # KURAL 2: NAKDİ UZLAŞMALI SÖZLEŞMELER (ENDEKS VİOP - F_XU030)
        # ---------------------------------------------------------------------
        elif info.settlement_type == SettlementType.CASH:
            if days_to_expiry == 0:
                # Vade günü
                if current_time.time() >= time(16, 0):
                    return (
                        RolloverAction.MANDATORY_CLOSE,
                        "Nakdi Uzlaşma Kuralı: Vade sonu günü saat 16:00 aşıldı! Son seans ZORUNLU KAPATMA."
                    )
                elif current_time.time() >= time(12, 0):
                    return (
                        RolloverAction.START_ROLLOVER,
                        "Nakdi Uzlaşma Kuralı: Vade sonu günü öğle seansı, yeni vadeye geçişi tamamlayın."
                    )
            elif days_to_expiry < 0:
                return (
                    RolloverAction.MANDATORY_CLOSE,
                    "Vade süresi doldu! ZORUNLU KAPATMA."
                )
            elif days_to_expiry <= 3:
                return (
                    RolloverAction.START_ROLLOVER,
                    f"Nakdi Uzlaşma Kuralı: Vadeye {days_to_expiry} gün kaldı, rollover döngüsü aktif."
                )

        return RolloverAction.MONITOR_ONLY, "Vade güvenli bölgede."

    def check_all_positions(self, current_time: datetime) -> Dict[str, Tuple[RolloverAction, str]]:
        """Kayıtlı tüm sözleşmeleri tarar ve gerekli eylemleri tetikler."""
        results = {}
        for symbol in self._contracts:
            action, reason = self.evaluate_contract_status(symbol, current_time)
            results[symbol] = (action, reason)
            if action == RolloverAction.MANDATORY_CLOSE:
                self._trigger_action(symbol, action, reason)
        return results

    def start(self) -> None:
        """Zamanlayıcıyı başlatır."""
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        """Zamanlayıcıyı durdurur."""
        if self.scheduler.running:
            self.scheduler.shutdown()
