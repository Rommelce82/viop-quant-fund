"""
Veri Modelleri ve Olay Tanımları Modülü.

Bu modül, sistemin uçtan uca tip güvenliğini ve 'Point-in-Time' veri bütünlüğünü
sağlayan veri yapılarını ve olaylarını içerir.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class MarketRegime(str, Enum):
    """Piyasa Rejim Sınıflandırması."""
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    RANGING_LOW_VOL = "RANGING_LOW_VOL"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


class SignalType(str, Enum):
    """Karar Motoru Sinyal Yönü."""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class OrderSide(str, Enum):
    """Emir Yönü."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Emir Tipi."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"


@dataclass(frozen=True)
class PointInTimeData:
    """
    Lookahead bias ve data leakage'ı engellemek için zaman damgalı temel/makro veri tabanı.
    
    Attributes:
        data_id: Benzersiz kayıt kimliği.
        symbol: İlgili hisse veya enstrüman.
        data_type: Veri türü ('FINANCIAL_STATEMENT', 'TCMB_POLICY_RATE', 'KAP_NEWS').
        as_of_date: Verinin ait olduğu bilanço dönemi / olay tarihi (Örn: 2024/09).
        announced_at: Verinin piyasaya fiilen açıklandığı / tescil edildiği zaman damgası.
        available_at: Verinin gecikme (latency) sonrası algoritmaya erişilebilir olduğu an.
        payload: Sayısal veya metin yükü (rasyolar, metinler vb.).
    """
    data_id: str
    symbol: str
    data_type: str
    as_of_date: datetime
    announced_at: datetime
    available_at: datetime
    payload: Dict[str, Any]

    def is_visible_at(self, current_time: datetime) -> bool:
        """Belirtilen simülasyon zamanında bu verinin erişilebilir olup olmadığını doğrular."""
        return current_time >= self.available_at


@dataclass(frozen=True)
class MarketBar:
    """
    Tekil Mum / Fiyat Verisi (OHLCV).
    """
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: Optional[float] = None


@dataclass
class EngineSignal:
    """
    Bir Karar Motorundan Üretilen Sinyal Çıktısı.
    """
    engine_name: str
    symbol: str
    timestamp: datetime
    signal_type: SignalType
    confidence_score: float  # [0.0 - 1.0]
    metrics: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


@dataclass
class ConsensusDecision:
    """
    3 Karar Motorunun Senkronize Tartışması ve Nihai Portföy Kararı.
    """
    symbol: str
    timestamp: datetime
    composite_score: float   # [-1.0 (Güçlü Sat) ile +1.0 (Güçlü Al)]
    target_action: SignalType
    regime: MarketRegime
    signals: Dict[str, EngineSignal]
    allocated_weight: float = 0.0


@dataclass
class Order:
    """
    VİOP Emir Nesnesi.
    """
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int            # Sözleşme adedi (kontrat sayısı)
    order_type: OrderType
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "PENDING"


@dataclass
class Position:
    """
    Açık VİOP Pozisyonu.
    """
    symbol: str
    quantity: int            # Pozitif: Uzun (Long), Negatif: Kısa (Short)
    average_entry_price: float
    current_price: float
    contract_multiplier: float
    initial_margin_per_contract: float
    trailing_stop_price: Optional[float] = None

    @property
    def market_value(self) -> float:
        """Pozisyonun toplam nominal piyasa değeri (TRY)."""
        return abs(self.quantity) * self.current_price * self.contract_multiplier

    @property
    def unrealized_pnl(self) -> float:
        """Açık pozisyon kar/zararı (TRY)."""
        return self.quantity * (self.current_price - self.average_entry_price) * self.contract_multiplier

    @property
    def total_required_initial_margin(self) -> float:
        """Bağlı toplam başlangıç teminatı."""
        return abs(self.quantity) * self.initial_margin_per_contract
