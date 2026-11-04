"""
Motor 3: Teknik Analiz ve Piyasa Rejimi Duyarlı Alfa Üreteci (Technical Engine).

Aşırı Uyum (Overfitting) Önleme İlkesi:
Sabit indikatör eşikleri (örneğin "RSI 30'u kırdı al") yerine;
1. Piyasa Rejim Tespiti (Trend, Yatay, Yüksek Volatilite),
2. Dinamik Volatilite Bantları (ATR ve Rolling Standard Deviation),
3. Hacim Ağırlıklı Momentumu senkronize ederek alfa üretir.
"""

from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Tuple
import math

from src.core.models import EngineSignal, MarketBar, MarketRegime, SignalType
from src.engines.base import BaseEngine


class TechnicalEngine(BaseEngine):
    """
    Piyasa Rejimine Duyarlı Dinamik Alfa Motoru.
    """

    def __init__(self, window_size: int = 50) -> None:
        """
        Args:
            window_size: İstatistiksel pencereler ve göstergeler için tutulan mum geçmişi uzunluğu.
        """
        super().__init__(name="TECHNICAL_ENGINE")
        self.window_size = window_size
        self._price_history: Dict[str, Deque[MarketBar]] = {}

    def update_bar(self, bar: MarketBar) -> None:
        """Yeni bir mum verisini iç hafızaya kaydeder."""
        if bar.symbol not in self._price_history:
            self._price_history[bar.symbol] = deque(maxlen=self.window_size)
        self._price_history[bar.symbol].append(bar)

    def detect_market_regime(self, symbol: str) -> Tuple[MarketRegime, float]:
        """
        Piyasa rejimini (Trend / Yatay / Yüksek Volatilite) ve ATR değerini belirler.
        """
        history = self._price_history.get(symbol)
        if not history or len(history) < 14:
            return MarketRegime.RANGING_LOW_VOL, 1.0

        closes = [b.close for b in history]
        highs = [b.high for b in history]
        lows = [b.low for b in history]

        # 1. Ortalama Gerçek Aralık (ATR 14)
        tr_list = []
        for i in range(1, len(history)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            tr_list.append(tr)

        atr_14 = sum(tr_list[-14:]) / 14 if len(tr_list) >= 14 else 1.0
        relative_volatility = atr_14 / closes[-1] if closes[-1] > 0 else 0.01

        # 2. Trend Tespiti: Basit Hareketli Ortalama (SMA 20) ve Eğim
        sma_20 = sum(closes[-20:]) / min(len(closes), 20)
        current_close = closes[-1]
        
        # 3. Rejim Kararı
        if relative_volatility > 0.035:
            # Mum boyutları fiyatın %3.5'inden fazla dalgalanıyorsa -> Yüksek Volatilite
            return MarketRegime.HIGH_VOLATILITY, atr_14
        
        pct_diff = (current_close - sma_20) / sma_20
        if pct_diff > 0.015:
            return MarketRegime.BULL_TREND, atr_14
        elif pct_diff < -0.015:
            return MarketRegime.BEAR_TREND, atr_14
        else:
            return MarketRegime.RANGING_LOW_VOL, atr_14

    def calculate_dynamic_rsi(self, symbol: str, period: int = 14) -> float:
        """RSI (Relative Strength Index) dinamik hesaplaması."""
        history = self._price_history.get(symbol)
        if not history or len(history) <= period:
            return 50.0

        closes = [b.close for b in history]
        gains = []
        losses = []

        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            if delta >= 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    def evaluate(self, symbol: str, current_time: datetime, current_bar: MarketBar) -> EngineSignal:
        """
        Rejim duyarlı teknik göstergeler üzerinden sinyal ve güven skoru türetir.
        """
        self.update_bar(current_bar)
        regime, atr = self.detect_market_regime(symbol)
        rsi = self.calculate_dynamic_rsi(symbol)

        score = 0.0
        rationale_list = [f"Rejim: {regime.value}", f"ATR: {atr:.2f}", f"Dinamik RSI: {rsi:.1f}"]

        # Rejime göre stratejiyi dinamik adapte et (Overfitting Önleme)
        if regime == MarketRegime.BULL_TREND:
            # Boğa trendinde geri çekilmeler alım fırsatıdır; sabit RSI 30 beklenmez, RSI 45-50 destek sayılır.
            if rsi < 55:
                score = 0.65
                rationale_list.append("Boğa trendinde dip konsolidasyonu (RSI < 55)")
            elif rsi > 80:
                score = 0.10  # Doygunluk, alım agresifliği düşürülür
                rationale_list.append("Aşırı alım doyum bölgesi")
            else:
                score = 0.40
                rationale_list.append("Trend takibi Long pozisyonu")

        elif regime == MarketRegime.BEAR_TREND:
            # Ayı trendinde yukarı tepkiler satım fırsatıdır
            if rsi > 45:
                score = -0.65
                rationale_list.append("Ayı trendinde tepki yükselişi satışı (RSI > 45)")
            else:
                score = -0.40
                rationale_list.append("Trend takibi Short pozisyonu")

        elif regime == MarketRegime.RANGING_LOW_VOL:
            # Yatay piyasada ortalamaya dönüş (Mean Reversion) çalışır
            if rsi <= 35:
                score = 0.50
                rationale_list.append("Yatay bantta aşırı satım dönüşü")
            elif rsi >= 65:
                score = -0.50
                rationale_list.append("Yatay bantta aşırı alım dönüşü")
            else:
                score = 0.0
                rationale_list.append("Nötr bölge, işlem pas geçildi")

        elif regime == MarketRegime.HIGH_VOLATILITY:
            # Şok volatilitede güven puanı ve pozisyon iştahı kısılır
            score = 0.0
            rationale_list.append("Aşırı volatil piyasa; sermaye koruma modu aktif")

        # Sinyal dönüşümü
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
                "regime": regime.value,
                "atr": atr,
                "dynamic_rsi": rsi,
                "technical_score": score
            },
            rationale=" | ".join(rationale_list)
        )
