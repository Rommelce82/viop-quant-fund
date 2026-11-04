"""
Ortak Zeka Teknik İcra Motoru (Technical Execution Engine).

Zaman Dilimleri:
- TF_Ana = Günlük (Daily) -> SMA(100) Ana Trend Filtresi
- TF_Tetik = 1 Saatlik (Hourly - 60m) -> ADX(14)/DMI(14) ve Donchian(20) Tetikleyicisi

Giriş Kuralları:
- B-Tarzı (Trend Takipçisi / Kırılım):
  * Günlük Kapanış > SMA(100) (Boğa Eğilimi)
  * Saatlik ADX >= 20 ve +DI > -DI (Trend Gücü)
  * Saatlik Kapanış >= Shift(1) Donchian High 20 (Zirve Kırılımı)
  * Hacim Patlaması: Saatlik Hacim >= 1.8 * SMA(20) Hacim (APS yoksa Fallback kuralı)
- A-Tarzı (Tepki / Aşırı Satım):
  * Yatay/Düşük ADX rejimi (ADX < 20)
  * Donchian Alt Bandına temas sonrası dönüş

Çatışma Çözümü (Lot vs. Kaldıraç):
- %2 NAV Risk Kuralı ile ideal lot hesaplanır: Lot = (NAV * 0.02) / (Risk_Per_Lot)
- Ancak yeni pozisyon ile birlikte Portföy Toplam Kaldıracı 2.2x tavanını aşıyorsa,
  Lot miktarı 2.2x sınırına TIRAŞLANIR (Cap).

Çıkış Kuralları:
- Zaman Stopu (Time Stop): bars_held >= 12 (1.5 iş günü) ve kâr < 1.0R ise kapat.
- Scale-Out: Kâr >= 1.5R ise kontratların %50'sini kapat, stopu başabaşa (Tapi) çek.
- Chandelier Exit: Kalan lotlar için 2.5x ATR iz süren stop işlet.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math
from typing import Dict, Optional, Tuple
import pandas as pd

from src.core.config import ContractSpecification, SystemConfig
from src.strategy.indicators import (
    calculate_adx_dmi,
    calculate_atr,
    calculate_donchian_channels
)
from src.strategy.position_manager import PositionState


class ExecutionAction(str, Enum):
    """İcra Motoru Karar Aksiyonu."""
    HOLD = "HOLD"
    ENTER_LONG_BREAKOUT = "ENTER_LONG_BREAKOUT"
    ENTER_LONG_REVERSAL = "ENTER_LONG_REVERSAL"
    SCALE_OUT_50 = "SCALE_OUT_50"
    TIME_STOP_EXIT = "TIME_STOP_EXIT"
    CHANDELIER_STOP_EXIT = "CHANDELIER_STOP_EXIT"


@dataclass
class ExecutionSignal:
    """İcra Sinyali ve Emir Detayı."""
    action: ExecutionAction
    symbol: str
    target_lots: int
    limit_price: float
    stop_price: float
    reason: str
    metrics: Dict[str, any]


class TechnicalExecutionEngine:
    """
    VİOP B-Tarzı ve A-Tarzı Çoklu Zaman Dilimli Teknik İcra Motoru.
    """

    MAX_PORTFOLIO_LEVERAGE = 2.2       # Anayasa Kesin Tavanı: 2.2x Kaldıraç
    RISK_PER_TRADE_PCT = 0.02          # İşlem Başına %2 NAV Riski
    TIME_STOP_BARS = 12                # 12 Saat (1.5 Borsa Günü)
    CHANDELIER_ATR_MULT = 2.5          # 2.5x ATR İz Süren Stop

    def __init__(self, config: Optional[SystemConfig] = None) -> None:
        self.config = config or SystemConfig()

    def calculate_lot_size_with_cap(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        portfolio_nav: float,
        current_portfolio_leverage: float
    ) -> Tuple[int, str]:
        """
        %2 NAV kuralı ile lot hesaplar; 2.2x kaldıraç tavanına göre tıraşlar (Cap).
        """
        spec = self.config.contracts.get(symbol)
        multiplier = spec.multiplier if spec else 100.0

        risk_per_point = abs(entry_price - stop_price)
        if risk_per_point <= 0.0:
            return 0, "Stop mesafesi sıfır veya negatif."

        # 1. %2 NAV Risk Bütçesi
        risk_budget_try = portfolio_nav * self.RISK_PER_TRADE_PCT
        risk_per_lot_try = risk_per_point * multiplier
        ideal_lots = int(risk_budget_try / risk_per_lot_try)

        if ideal_lots <= 0:
            return 0, "Risk bütçesi 1 lot açmaya yetmiyor."

        # 2. Kaldıraç Kısıtı: Maksimum 2.2x
        # Açık pozisyon nominal değeri = Lots * Fiyat * Çarpan
        current_notional = portfolio_nav * current_portfolio_leverage
        max_total_notional = portfolio_nav * self.MAX_PORTFOLIO_LEVERAGE
        available_notional = max(0.0, max_total_notional - current_notional)

        lot_notional_value = entry_price * multiplier
        max_lots_by_leverage = int(available_notional / lot_notional_value) if lot_notional_value > 0 else 0

        # Çatışma Çözümü: Tıraşlama
        if ideal_lots > max_lots_by_leverage:
            capped_lots = max_lots_by_leverage
            reason = (
                f"Kaldıraç Tıraşlaması: %2 NAV kuralı {ideal_lots} lot önerdi, "
                f"ancak 2.2x kaldıraç sınırı nedeniyle {capped_lots} lota tıraşlandı."
            )
            return capped_lots, reason
        else:
            return ideal_lots, f"Risk bütçesi onaylandı ({ideal_lots} lot, kaldıraç sınırı içinde)."

    def evaluate_execution(
        self,
        symbol: str,
        daily_data: pd.DataFrame,
        hourly_data: pd.DataFrame,
        position_state: Optional[PositionState],
        macro_permission: bool,
        portfolio_nav: float,
        current_portfolio_leverage: float
    ) -> ExecutionSignal:
        """
        Günlük (Trend) ve Saatlik (Tetik) verileri birleştirerek icra sinyali üretir.
        """
        current_hourly_bar = hourly_data.iloc[-1]
        current_price = float(current_hourly_bar["close"])

        # ---------------------------------------------------------------------
        # 1. MEVCUT AÇIK POZİSYONUN ÇIKIŞ YÖNETİMİ
        # ---------------------------------------------------------------------
        if position_state and position_state.is_active:
            position_state.increment_bars_held()
            r_multiple = position_state.get_current_r_multiple(current_price)

            # A. KURAL: Zaman Stopu (bars_held >= 12 ve Kâr < 1.0R)
            if position_state.bars_held >= self.TIME_STOP_BARS and r_multiple < 1.0:
                return ExecutionSignal(
                    action=ExecutionAction.TIME_STOP_EXIT,
                    symbol=symbol,
                    target_lots=position_state.lots,
                    limit_price=current_price,
                    stop_price=current_price,
                    reason=f"Zaman Stopu: {position_state.bars_held} bar geçti ve getiri {r_multiple:.2f}R < 1.0R. Pozisyon tasfiye edildi.",
                    metrics={"bars_held": position_state.bars_held, "r_multiple": r_multiple}
                )

            # B. KURAL: Scale-Out (%50 Kâr Realizasyonu ve Başa Baş - Tapi Çekimi)
            if r_multiple >= 1.5 and not position_state.scaled_out and position_state.lots > 1:
                close_lots = position_state.lots // 2
                position_state.scaled_out = True
                position_state.lots -= close_lots
                # Stopu maliyet seviyesine (Tapi) çek
                position_state.trailing_stop = position_state.entry_price

                return ExecutionSignal(
                    action=ExecutionAction.SCALE_OUT_50,
                    symbol=symbol,
                    target_lots=close_lots,
                    limit_price=current_price,
                    stop_price=position_state.entry_price,
                    reason=f"Scale-Out: {r_multiple:.2f}R kâr hedefine ulaşıldı. %50 ({close_lots} lot) kapatıldı, stop maliyete çekildi.",
                    metrics={"r_multiple": r_multiple, "remaining_lots": position_state.lots}
                )

            # C. KURAL: Chandelier Exit (2.5x ATR İz Süren Stop)
            hourly_atr = float(calculate_atr(hourly_data, period=14).iloc[-1])
            new_chandelier_stop = round(current_hourly_bar["high"] - (self.CHANDELIER_ATR_MULT * hourly_atr), 2)
            
            # İz süren stop sadece lehte (yukarı) güncellenir
            if new_chandelier_stop > position_state.trailing_stop:
                position_state.trailing_stop = new_chandelier_stop

            # Stop ihlali kontrolü
            if current_hourly_bar["low"] <= position_state.trailing_stop:
                return ExecutionSignal(
                    action=ExecutionAction.CHANDELIER_STOP_EXIT,
                    symbol=symbol,
                    target_lots=position_state.lots,
                    limit_price=position_state.trailing_stop,
                    stop_price=position_state.trailing_stop,
                    reason=f"Chandelier Exit: İz süren stop ({position_state.trailing_stop} TL) ihlal edildi. Kalan lotlar kapatıldı.",
                    metrics={"trailing_stop": position_state.trailing_stop, "atr": hourly_atr}
                )

            # Pozisyon devam ediyor
            return ExecutionSignal(
                action=ExecutionAction.HOLD,
                symbol=symbol,
                target_lots=position_state.lots,
                limit_price=current_price,
                stop_price=position_state.trailing_stop,
                reason=f"Pozisyon Korunuyor (Bar: {position_state.bars_held}, Kâr: {r_multiple:.2f}R, Stop: {position_state.trailing_stop} TL)",
                metrics={"bars_held": position_state.bars_held, "trailing_stop": position_state.trailing_stop}
            )

        # ---------------------------------------------------------------------
        # 2. YENİ POZİSYON GİRİŞ DEĞERLENDİRMESİ
        # ---------------------------------------------------------------------
        if not macro_permission:
            return ExecutionSignal(
                action=ExecutionAction.HOLD,
                symbol=symbol,
                target_lots=0,
                limit_price=current_price,
                stop_price=0.0,
                reason="Makro İklim İzni Yok (TCMB / Nötr Bekleme Kalkanı Aktif). Yeni işlem yasak.",
                metrics={}
            )

        # A. TF_Ana: Günlük SMA(100) Trend Kontrolü
        daily_sma_100 = daily_data["close"].rolling(window=100, min_periods=50).mean().iloc[-1]
        daily_close = float(daily_data["close"].iloc[-1])
        is_daily_bullish = daily_close >= daily_sma_100

        # B. TF_Tetik: Saatlik ADX ve DMI Kontrolü
        adx, plus_di, minus_di = calculate_adx_dmi(hourly_data, period=14)
        latest_adx = float(adx.iloc[-1])
        latest_plus = float(plus_di.iloc[-1])
        latest_minus = float(minus_di.iloc[-1])
        is_trending = latest_adx >= 20.0 and (latest_plus > latest_minus)

        # C. Saatlik Donchian Kanalları (Shift 1 - Lookahead Bias Önlemeli)
        don_high, don_low, don_mid = calculate_donchian_channels(hourly_data, period=20)
        prev_don_high = float(don_high.iloc[-1])
        is_breakout = current_price >= prev_don_high

        # D. Saatlik Hacim Patlaması (APS Fallback Kuralı: Volume >= 1.8 * SMA20)
        vol_sma20 = hourly_data["volume"].rolling(window=20, min_periods=5).mean().iloc[-1]
        latest_vol = float(current_hourly_bar["volume"])
        is_volume_spike = latest_vol >= (1.8 * vol_sma20)

        # ATR Hesabı (Stop Belirleme)
        hourly_atr = float(calculate_atr(hourly_data, period=14).iloc[-1])
        stop_price = round(current_price - (2.0 * hourly_atr), 2)

        # B-TARZI KIRILIM GİRİŞİ:
        # Günlük Bullish + Saatlik Trend Gücü + Donchian High Kırılımı + Hacim Patlaması
        if is_daily_bullish and is_trending and is_breakout and is_volume_spike:
            lots, sizing_reason = self.calculate_lot_size_with_cap(
                symbol=symbol,
                entry_price=current_price,
                stop_price=stop_price,
                portfolio_nav=portfolio_nav,
                current_portfolio_leverage=current_portfolio_leverage
            )

            if lots > 0:
                return ExecutionSignal(
                    action=ExecutionAction.ENTER_LONG_BREAKOUT,
                    symbol=symbol,
                    target_lots=lots,
                    limit_price=current_price,
                    stop_price=stop_price,
                    reason=f"B-Tarzı Kırılım Onaylandı: {sizing_reason}",
                    metrics={
                        "daily_close": daily_close,
                        "daily_sma100": daily_sma_100,
                        "hourly_adx": latest_adx,
                        "prev_donchian_high": prev_don_high,
                        "volume_ratio": latest_vol / max(1.0, vol_sma20),
                        "atr": hourly_atr
                    }
                )

        # Giriş koşulları sağlanmadı
        return ExecutionSignal(
            action=ExecutionAction.HOLD,
            symbol=symbol,
            target_lots=0,
            limit_price=current_price,
            stop_price=0.0,
            reason="Giriş kriterleri oluşmadı (Nötr Bekleme).",
            metrics={
                "is_daily_bullish": is_daily_bullish,
                "is_trending": is_trending,
                "is_breakout": is_breakout,
                "is_volume_spike": is_volume_spike
            }
        )
