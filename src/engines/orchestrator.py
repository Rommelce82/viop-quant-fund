"""
Karar Motorları Orkestratörü ve Konsensüs Mekanizması.

3 Farklı Bağımsız Motoru (Temel, Haber/Duyarlılık, Teknik) senkronize ederek
ağırlıklı puanlama ile nihai sermaye tahsis kararını (Consensus Decision) üretir.
"""

from datetime import datetime
from typing import Dict
from src.core.models import ConsensusDecision, MarketBar, MarketRegime, SignalType
from src.engines.fundamental import FundamentalEngine
from src.engines.sentiment import SentimentEngine
from src.engines.technical import TechnicalEngine


class StrategyOrchestrator:
    """
    3 Motorlu Konsensüs Karar Orkestratörü.
    """

    def __init__(
        self,
        fundamental_engine: FundamentalEngine,
        sentiment_engine: SentimentEngine,
        technical_engine: TechnicalEngine,
        weight_fundamental: float = 0.35,
        weight_sentiment: float = 0.25,
        weight_technical: float = 0.40
    ) -> None:
        """
        Motor ağırlıklarını normalize ederek ilklendirir.
        """
        self.fundamental = fundamental_engine
        self.sentiment = sentiment_engine
        self.technical = technical_engine

        total_weight = weight_fundamental + weight_sentiment + weight_technical
        self.w_fund = weight_fundamental / total_weight
        self.w_sent = weight_sentiment / total_weight
        self.w_tech = weight_technical / total_weight

    def _signal_to_numeric(self, signal_type: SignalType, confidence: float) -> float:
        """Sinyal yönü ve güven skorunu [-1.0, 1.0] aralığında sürekli sayıya dönüştürür."""
        multiplier_map = {
            SignalType.STRONG_BUY: 1.0,
            SignalType.BUY: 0.6,
            SignalType.NEUTRAL: 0.0,
            SignalType.SELL: -0.6,
            SignalType.STRONG_SELL: -1.0
        }
        return multiplier_map[signal_type] * confidence

    def decide(self, symbol: str, current_time: datetime, current_bar: MarketBar) -> ConsensusDecision:
        """
        3 motoru eşzamanlı çalıştırır, rejim ve konsensüs kurallarına göre nihai kararı verir.
        """
        sig_fund = self.fundamental.evaluate(symbol, current_time, current_bar)
        sig_sent = self.sentiment.evaluate(symbol, current_time, current_bar)
        sig_tech = self.technical.evaluate(symbol, current_time, current_bar)

        score_fund = self._signal_to_numeric(sig_fund.signal_type, sig_fund.confidence_score)
        score_sent = self._signal_to_numeric(sig_sent.signal_type, sig_sent.confidence_score)
        score_tech = self._signal_to_numeric(sig_tech.signal_type, sig_tech.confidence_score)

        # Kompozit Puan
        composite = (
            self.w_fund * score_fund +
            self.w_sent * score_sent +
            self.w_tech * score_tech
        )

        regime_str = sig_tech.metrics.get("regime", MarketRegime.RANGING_LOW_VOL.value)
        regime = MarketRegime(regime_str)

        # Şok Volatilitede pozisyon açma riskini sıfırla/kıs (Sermaye koruma kuralı)
        if regime == MarketRegime.HIGH_VOLATILITY:
            composite *= 0.20

        # Nihai Karar ve Eşik Değerleri
        if composite >= 0.40:
            target_action = SignalType.STRONG_BUY
        elif composite >= 0.15:
            target_action = SignalType.BUY
        elif composite <= -0.40:
            target_action = SignalType.STRONG_SELL
        elif composite <= -0.15:
            target_action = SignalType.SELL
        else:
            target_action = SignalType.NEUTRAL

        return ConsensusDecision(
            symbol=symbol,
            timestamp=current_time,
            composite_score=composite,
            target_action=target_action,
            regime=regime,
            signals={
                "FUNDAMENTAL": sig_fund,
                "SENTIMENT": sig_sent,
                "TECHNICAL": sig_tech
            },
            allocated_weight=abs(composite)
        )
