"""
Motor 1: Temel Analiz ve Evren Seçimi (Fundamental Universe Selection Engine).

Bu motor, Fintables PRO ve TCMB verilerini kullanarak 'Point-in-Time' esasına göre
hisseleri değerleme (Valuation), karlılık (Profitability), borçluluk (Leverage)
ve büyüme (Growth) metriklerine göre filtreler.
"""

from datetime import datetime
from typing import Dict, List, Optional
from src.core.models import EngineSignal, MarketBar, SignalType
from src.data.fintables_pipeline import FintablesPipeline
from src.data.tcmb_pipeline import TCMBPipeline
from src.engines.base import BaseEngine


class FundamentalEngine(BaseEngine):
    """
    Kantitatif Temel Analiz ve Evren Seçim Motoru.
    """

    def __init__(
        self,
        fintables_pipeline: FintablesPipeline,
        tcmb_pipeline: TCMBPipeline
    ) -> None:
        """
        Args:
            fintables_pipeline: Fintables PIT veri hattı.
            tcmb_pipeline: TCMB makro veri hattı.
        """
        super().__init__(name="FUNDAMENTAL_ENGINE")
        self.fintables = fintables_pipeline
        self.tcmb = tcmb_pipeline

    def evaluate(self, symbol: str, current_time: datetime, current_bar: MarketBar) -> EngineSignal:
        """
        Şirketin bilançosunu ve makro faiz ortamını analiz ederek temel puan üretir.
        """
        financials = self.fintables.get_latest_statement(symbol, current_time)
        macro = self.tcmb.get_latest_macro_state(current_time)

        if not financials:
            return EngineSignal(
                engine_name=self.name,
                symbol=symbol,
                timestamp=current_time,
                signal_type=SignalType.NEUTRAL,
                confidence_score=0.0,
                metrics={"status": "NO_AVAILABLE_PIT_DATA"},
                rationale="Belirtilen tarihte açıklanmış geçerli bilanço bulunamadı."
            )

        data = financials.payload
        pe = data.get("pe_ratio", 20.0)
        pb = data.get("pb_ratio", 3.0)
        roe = data.get("roe", 0.10)
        net_profit_growth = data.get("net_profit_growth", 0.0)
        net_debt_ebitda = data.get("net_debt_ebitda", 2.0)

        # Temel Skorlama Algoritması: Değerleme & Karlılık Filtresi
        score = 0.0
        reasons = []

        # 1. F/K Değerlendirmesi
        if pe < 6.0:
            score += 0.30
            reasons.append("Çok Cazip F/K (<6)")
        elif pe < 10.0:
            score += 0.15
            reasons.append("Makul F/K (<10)")
        elif pe > 25.0:
            score -= 0.25
            reasons.append("Yüksek Değerleme F/K (>25)")

        # 2. Özsermaye Karlılığı (ROE)
        if roe > 0.30:
            score += 0.30
            reasons.append("Yüksek ROE (>%30)")
        elif roe > 0.20:
            score += 0.15
            reasons.append("Ortalama Üstü ROE (>%20)")
        elif roe < 0.10:
            score -= 0.20
            reasons.append("Zayıf Sermaye Getirisi ROE (<%10)")

        # 3. Kar Büyümesi
        if net_profit_growth > 0.25:
            score += 0.25
            reasons.append("Güçlü Net Kar Büyümesi (>%25)")
        elif net_profit_growth < 0.0:
            score -= 0.20
            reasons.append("Daralan Kar Büyümesi")

        # 4. Borçluluk (Faizlerin yüksek olduğu ortamda borçluluk cezası)
        policy_rate = macro.payload.get("policy_rate", 45.0) if macro else 45.0
        if policy_rate >= 40.0 and net_debt_ebitda > 2.5:
            score -= 0.25
            reasons.append("Yüksek Faiz Ortamında Kritik Borçluluk (Net Borç/FAVÖK > 2.5)")
        elif net_debt_ebitda <= 1.0:
            score += 0.15
            reasons.append("Düşük Borç Yükü")

        # Skor sınırlandırma [-1.0, 1.0]
        score = max(-1.0, min(1.0, score))

        # Sinyal Yönü
        if score >= 0.50:
            signal_type = SignalType.STRONG_BUY
        elif score >= 0.20:
            signal_type = SignalType.BUY
        elif score <= -0.50:
            signal_type = SignalType.STRONG_SELL
        elif score <= -0.20:
            signal_type = SignalType.SELL
        else:
            signal_type = SignalType.NEUTRAL

        return EngineSignal(
            engine_name=self.name,
            symbol=symbol,
            timestamp=current_time,
            signal_type=signal_type,
            confidence_score=abs(score),
            metrics={
                "pe_ratio": pe,
                "roe": roe,
                "growth": net_profit_growth,
                "net_debt_ebitda": net_debt_ebitda,
                "macro_rate": policy_rate,
                "composite_fundamental_score": score
            },
            rationale=", ".join(reasons)
        )
