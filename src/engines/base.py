"""
Temel Karar Motoru Taban Arayüzü.

Tüm strateji motorları (Temel, Haber, Teknik) bu sınıftan türetilir.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from src.core.models import EngineSignal, MarketBar


class BaseEngine(ABC):
    """
    Karar Motoru Soyut Temel Sınıfı.
    """

    def __init__(self, name: str) -> None:
        """
        Args:
            name: Motorun benzersiz adı.
        """
        self.name: str = name

    @abstractmethod
    def evaluate(self, symbol: str, current_time: datetime, current_bar: MarketBar) -> EngineSignal:
        """
        Belirtilen zaman diliminde sembol için sinyal üretir.
        
        Args:
            symbol: Enstrüman veya hisse sembolü.
            current_time: Mevcut an (simülasyon saati).
            current_bar: O anki mum/fiyat verisi.
            
        Returns:
            EngineSignal: Üretilen al/sat veya nötr sinyali ve güven skoru.
        """
        pass
