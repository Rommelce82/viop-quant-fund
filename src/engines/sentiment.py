"""
Motor 2: Haber ve KAP Duyarlılık Motoru (KAP / News Sentiment Engine).

Bu motor, Kamu Aydınlatma Platformu (KAP) bildirimlerini, şirket haberlerini
ve makro bültenleri 'Point-in-Time' gecikme süresini (latency) gözeterek inceler.
Kelimeler, şirket operasyonel gelişmeleri ve ihale/pay geri alım bildirimlerini
duyarlılık (sentiment) skoruna dönüştürür.
"""

from datetime import datetime
from typing import Dict, List, Optional
from src.core.models import EngineSignal, MarketBar, PointInTimeData, SignalType
from src.engines.base import BaseEngine


class SentimentEngine(BaseEngine):
    """
    KAP ve Haber Duyarlılık Skorlama Motoru.
    """

    def __init__(self, latency_seconds: float = 2.0) -> None:
        """
        Args:
            latency_seconds: Bilginin algoritmaya erişim gecikmesi.
        """
        super().__init__(name="SENTIMENT_ENGINE")
        self.latency_seconds = latency_seconds
        self._news_db: List[PointInTimeData] = []
        
        # Basit NLP Duyarlılık Sözlüğü (Türkçe Finansal Terimler)
        self.positive_keywords: Dict[str, float] = {
            "pay geri alım": 0.60,
            "ihale kazan": 0.70,
            "yeni iş ilişkisi": 0.50,
            "rekor kar": 0.65,
            "kapasite artış": 0.45,
            "sözleşme imza": 0.55,
            "temettü dağıtım": 0.40,
            "not artış": 0.60,
            "hedef fiyat yüksel": 0.40
        }
        self.negative_keywords: Dict[str, float] = {
            "dava açıl": -0.50,
            "üretim durdur": -0.75,
            "zarar açıkla": -0.60,
            "sözleşme fesih": -0.70,
            "grev": -0.55,
            "soruşturma": -0.60,
            "not indir": -0.65,
            "vergi ceza": -0.60
        }

    def register_news_item(self, record: PointInTimeData) -> None:
        """KAP veya haber bildirimini Point-in-Time veritabanına ekler."""
        self._news_db.append(record)

    def load_mock_news(self) -> None:
        """Örnek KAP bildirimlerini yükler."""
        # THYAO: Yeni uçak siparişi ve filo büyümesi
        self._news_db.append(
            PointInTimeData(
                data_id="KAP_THYAO_1",
                symbol="THYAO",
                data_type="KAP_NEWS",
                as_of_date=datetime(2024, 8, 16, 9, 0),
                announced_at=datetime(2024, 8, 16, 9, 0),
                available_at=datetime(2024, 8, 16, 9, 0, 2),
                payload={
                    "headline": "THYAO Yeni Uçak Alımı ve Kapasite Artışı Hakkında",
                    "content": "Şirketimiz küresel büyüme hedefleri doğrultusunda yeni uçak alımı için sözleşme imzalamış ve kapasite artış kararı almıştır."
                }
            )
        )
        # EREGL: Fabrika bakım duruşu
        self._news_db.append(
            PointInTimeData(
                data_id="KAP_EREGL_1",
                symbol="EREGL",
                data_type="KAP_NEWS",
                as_of_date=datetime(2024, 8, 10, 17, 45),
                announced_at=datetime(2024, 8, 10, 17, 45),
                available_at=datetime(2024, 8, 10, 17, 45, 2),
                payload={
                    "headline": "EREGL Yüksek Fırın Revizyonu ve Geçici Üretim Durdurulması",
                    "content": "Şirketimiz 2 nolu yüksek fırında planlı revizyon nedeniyle üretim durdurma kararı almıştır."
                }
            )
        )

    def evaluate(self, symbol: str, current_time: datetime, current_bar: MarketBar) -> EngineSignal:
        """
        Şirketin 'current_time' anına kadar yayınlanmış son 48 saatlik KAP haberlerini
        tarar ve net duyarlılık skoru üretir.
        """
        # Son 48 saatteki ve şu an erişilebilir olan haberleri al
        two_days_ago = current_time.timestamp() - (48 * 3600)
        relevant_news = [
            news for news in self._news_db
            if news.symbol == symbol and news.is_visible_at(current_time)
            and news.announced_at.timestamp() >= two_days_ago
        ]

        if not relevant_news:
            return EngineSignal(
                engine_name=self.name,
                symbol=symbol,
                timestamp=current_time,
                signal_type=SignalType.NEUTRAL,
                confidence_score=0.0,
                metrics={"news_count": 0, "sentiment_score": 0.0},
                rationale="Son 48 saatte aktif KAP bildirimi bulunmuyor."
            )

        total_score = 0.0
        detected_keywords = []

        for news in relevant_news:
            text = (news.payload.get("headline", "") + " " + news.payload.get("content", "")).lower()
            
            for kw, impact in self.positive_keywords.items():
                if kw in text:
                    total_score += impact
                    detected_keywords.append(f"+{kw}")

            for kw, impact in self.negative_keywords.items():
                if kw in text:
                    total_score += impact
                    detected_keywords.append(f"-{kw}")

        # Normalize et [-1.0, 1.0]
        clamped_score = max(-1.0, min(1.0, total_score))

        if clamped_score >= 0.40:
            signal_type = SignalType.STRONG_BUY
        elif clamped_score >= 0.15:
            signal_type = SignalType.BUY
        elif clamped_score <= -0.40:
            signal_type = SignalType.STRONG_SELL
        elif clamped_score <= -0.15:
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.NEUTRAL

        return EngineSignal(
            engine_name=self.name,
            symbol=symbol,
            timestamp=current_time,
            signal_type=signal_type,
            confidence_score=abs(clamped_score),
            metrics={
                "news_count": len(relevant_news),
                "sentiment_score": clamped_score,
                "keywords": detected_keywords
            },
            rationale=f"KAP Duyarlılık analizi ({len(relevant_news)} haber): {', '.join(detected_keywords) if detected_keywords else 'Nötr'}"
        )
