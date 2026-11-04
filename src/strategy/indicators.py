"""
Teknik Göstergeler Modülü (Indicators).

Bu modül;
- ADX (Average Directional Index) ve DMI (+DI, -DI),
- ATR (Average True Range),
- Donchian Kanalları (High_N, Low_N)
fonksiyonlarını içerir.

Lookahead Bias (Gelecekten Bilgi Alma) Koruması:
Kırılım (Breakout) tespitinde mevcut barın kapanış fiyatı, daima bir önceki barın
Donchian tavan/tabanına (shift(1)) göre kıyaslanır. Asla mevcut barın dahil olduğu
güncel tepe kullanılmaz!
"""

import math
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Ortalama Gerçek Aralık (Average True Range - ATR).
    
    True Range = max(High - Low, |High - Close_prev|, |Low - Close_prev|)
    Sıfıra bölünme ve boş seri korumalıdır.
    """
    if df.empty or len(df) < 2:
        return pd.Series(index=df.index, dtype=float).fillna(1.0)

    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Wilder's Smoothing / RMA ile ATR
    atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return atr.bfill().fillna(1.0)


def calculate_adx_dmi(
    df: pd.DataFrame,
    period: int = 14
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    ADX (Trend Gücü) ve DMI (+DI, -DI) Hesaplayıcı.
    
    Formüller:
    +DM = High_t - High_{t-1} (eğer > 0 ve > Low_{t-1} - Low_t)
    -DM = Low_{t-1} - Low_t (eğer > 0 ve > High_t - High_{t-1})
    DX = 100 * |+DI - -DI| / (|+DI + -DI|)
    ADX = DX'in Wilder yumuşatması.
    
    Returns:
        (adx, plus_di, minus_di)
    """
    if df.empty or len(df) < period + 1:
        zeros = pd.Series(0.0, index=df.index)
        return zeros, zeros, zeros

    high = df["high"]
    low = df["low"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_series = pd.Series(plus_dm, index=df.index)
    minus_dm_series = pd.Series(minus_dm, index=df.index)

    atr = calculate_atr(df, period=period)

    # Düzeltilmiş Wilder hareketli ortalamaları
    smoothed_plus_dm = plus_dm_series.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    smoothed_minus_dm = minus_dm_series.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    # Sıfıra bölünme koruması
    safe_atr = atr.replace(0.0, 1e-6)
    plus_di = 100.0 * (smoothed_plus_dm / safe_atr)
    minus_di = 100.0 * (smoothed_minus_dm / safe_atr)

    di_sum = (plus_di + minus_di).replace(0.0, 1e-6)
    dx = 100.0 * ((plus_di - minus_di).abs() / di_sum)

    adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return adx.bfill().fillna(0.0), plus_di.bfill().fillna(0.0), minus_di.bfill().fillna(0.0)


def calculate_donchian_channels(
    df: pd.DataFrame,
    period: int = 20
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Donchian Kanalları (High_N, Low_N, Mid_N).
    
    LOOKAHEAD BIAS KORUMASI:
    Dönen Donchian serisi 'shift(1)' yapılmış olarak verilir.
    Böylece t anındaki bir mumun tepe/dip fiyatı, t anındaki kanalı DEĞİŞTİREMEZ.
    Kırılım teyidi = close_t >= donchian_high_prev_t
    
    Returns:
        (shifted_donchian_high, shifted_donchian_low, shifted_donchian_mid)
    """
    if df.empty:
        zeros = pd.Series(index=df.index, dtype=float)
        return zeros, zeros, zeros

    raw_high = df["high"].rolling(window=period, min_periods=1).max()
    raw_low = df["low"].rolling(window=period, min_periods=1).min()
    
    # 1 Bar geriye kaydır (Shift 1) -> Sadece geçmiş barlardan oluşan kanal
    shifted_high = raw_high.shift(1).bfill()
    shifted_low = raw_low.shift(1).bfill()
    shifted_mid = (shifted_high + shifted_low) / 2.0

    return shifted_high, shifted_low, shifted_mid


def calculate_diosc(
    df: pd.DataFrame,
    adx_period: int = 14,
    signal_period: int = 9
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    DIOSC (Directional Indicator Oscillator) ve Sinyal Çizgisi.
    
    DIOSC = (+DI) - (-DI)
    Sinyal = DIOSC'un signal_period (9) günlük/saatlik SMA'sı.
    Kesişim = DIOSC'un kendi SMA9'unu yukarı (bullish) veya aşağı (bearish) kesmesi.
    
    Returns:
        (diosc, diosc_signal, diosc_hist)
    """
    if df.empty or len(df) < adx_period:
        zeros = pd.Series(0.0, index=df.index)
        return zeros, zeros, zeros

    _, plus_di, minus_di = calculate_adx_dmi(df, period=adx_period)
    diosc = plus_di - minus_di
    diosc_signal = diosc.rolling(window=signal_period, min_periods=1).mean()
    diosc_hist = diosc - diosc_signal

    return diosc, diosc_signal, diosc_hist


def calculate_ema(series: pd.Series, period: int = 20) -> pd.Series:
    """Üstel Hareketli Ortalama (EMA)."""
    if series.empty:
        return series
    return series.ewm(span=period, adjust=False).mean()


def calculate_sma(series: pd.Series, period: int = 20) -> pd.Series:
    """Basit Hareketli Ortalama (SMA)."""
    if series.empty:
        return series
    return series.rolling(window=period, min_periods=1).mean()


def calculate_bollinger_bands(
    series: pd.Series,
    period: int = 20,
    num_std: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bantları: Üst, Orta (SMA), Alt.
    """
    if series.empty:
        return series, series, series
    mid = series.rolling(window=period, min_periods=1).mean()
    std = series.rolling(window=period, min_periods=1).std().fillna(0.0)
    upper = mid + (num_std * std)
    lower = mid - (num_std * std)
    return upper, mid, lower


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Göreceli Güç Endeksi (RSI - Wilder Smoothing).
    """
    if series.empty or len(series) < 2:
        return pd.Series(50.0, index=series.index)
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, 1e-6)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.bfill().fillna(50.0)

