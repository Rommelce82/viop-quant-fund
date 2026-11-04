"""
Teknik İcra Motoru Doğrulama ve Konsol Testi (test_technical_engine.py).

Bu test betiği;
1. Günlük ve Saatlik sentetik fiyat serileri oluşturur,
2. B-Tarzı kırılım oluşumunu (Donchian High, ADX > 20, Hacim Patlaması) simüle eder,
3. %2 NAV kuralı ile lot hesaplar ve 2.2x kaldıraç tavanına göre tıraşlamayı (Cap) doğrular,
4. Pozisyon açıldıktan sonra 12 bar boyunca piyasayı yatay/düşük kârda tutarak Zaman Stopu (Time Stop)
   ile pozisyonun zorunlu tasfiyesini konsolda kanıtlar.
"""

from datetime import datetime, timedelta
import sys
import numpy as np
import pandas as pd

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.strategy.position_manager import PositionState
from src.strategy.technical_engine import ExecutionAction, TechnicalExecutionEngine


def generate_synthetic_market_data():
    """Test için gerçekçi Günlük ve Saatlik mum serileri üretir."""
    # 1. Günlük Veri (120 Bar): Yükselen trend (SMA100 üzerinde)
    daily_dates = [datetime(2026, 5, 1) + timedelta(days=i) for i in range(120)]
    daily_closes = [250.0 + (i * 0.5) for i in range(120)]
    daily_df = pd.DataFrame({
        "timestamp": daily_dates,
        "open": [c - 1.0 for c in daily_closes],
        "high": [c + 2.0 for c in daily_closes],
        "low": [c - 2.0 for c in daily_closes],
        "close": daily_closes,
        "volume": [50_000_000.0 for _ in range(120)]
    })

    # 2. Saatlik Veri (50 Bar):
    # İlk 48 bar konsolidasyon (305 - 310 TL bandı), 49. barda patlama ve kırılım (312 TL)
    hourly_dates = [datetime(2026, 10, 1, 9, 0) + timedelta(hours=i) for i in range(50)]
    hourly_highs = []
    hourly_lows = []
    hourly_closes = []
    hourly_volumes = []

    for i in range(49):
        c = 308.0 + np.sin(i / 3.0) * 2.0
        hourly_closes.append(c)
        hourly_highs.append(c + 1.2)
        hourly_lows.append(c - 1.2)
        hourly_volumes.append(100_000.0)

    # 49. Bar: Kırılım Barı (Donchian High 310'u kırarak 314'e fırlıyor, hacim 2.5x patlıyor)
    hourly_closes.append(314.0)
    hourly_highs.append(315.0)
    hourly_lows.append(309.0)
    hourly_volumes.append(280_000.0)  # 2.8x Hacim patlaması

    hourly_df = pd.DataFrame({
        "timestamp": hourly_dates,
        "open": [c - 0.5 for c in hourly_closes],
        "high": hourly_highs,
        "low": hourly_lows,
        "close": hourly_closes,
        "volume": hourly_volumes
    })

    return daily_df, hourly_df


def run_technical_engine_test():
    print("=" * 80)
    print("  TEKNİK İCRA MOTORU, B-TARZI KIRILIM, KALDIRAÇ TIRAŞLAMA VE ZAMAN STOPU TESTİ")
    print("=" * 80)

    daily_df, hourly_df = generate_synthetic_market_data()
    engine = TechnicalExecutionEngine()

    symbol = "F_THYAO"
    portfolio_nav = 1_000_000.0          # 1 Milyon TL NAV
    current_leverage = 1.80               # Portföyde halihazırda 1.80x kaldıraç var (Tavan: 2.2x)

    print("\n[+] 1. ADIM: B-TARZI KIRILIM VE KALDIRAÇ TIRAŞLAMA (CAP) TESTİ:")
    print(f"    * Portföy NAV               : {portfolio_nav:,.2f} TL")
    print(f"    * Mevcut Portföy Kaldıracı : {current_leverage:.2f}x (İzin Verilen Tavan: 2.20x)")
    print(f"    * Kalan Kaldıraç Marjı      : {2.20 - current_leverage:.2f}x (En fazla 400,000 TL nominal pozisyon açılabilir)")

    signal = engine.evaluate_execution(
        symbol=symbol,
        daily_data=daily_df,
        hourly_data=hourly_df,
        position_state=None,
        macro_permission=True,
        portfolio_nav=portfolio_nav,
        current_portfolio_leverage=current_leverage
    )

    print(f"\n    -> ÜRETİLEN SİNYAL: {signal.action.value}")
    print(f"    -> Kontrat Adedi  : {signal.target_lots} Lot (Sözleşme Çarpanı: 100)")
    print(f"    -> Giriş Fiyatı   : {signal.limit_price:.2f} TL | Stop Fiyatı: {signal.stop_price:.2f} TL")
    print(f"    -> Gerekçe        : {signal.reason}")

    # Kaldıraç kontrolü doğrulaması:
    # 400.000 TL nominal / (314 TL * 100) = ~12.7 lot -> Tıraşlanmış Lot = 12 lot olmalıdır
    nominal_opened = signal.target_lots * signal.limit_price * 100.0
    new_leverage = current_leverage + (nominal_opened / portfolio_nav)
    print(f"    -> Açılan Nominal : {nominal_opened:,.2f} TL | Yeni Toplam Kaldıraç: {new_leverage:.2f}x <= 2.20x")
    assert signal.action == ExecutionAction.ENTER_LONG_BREAKOUT, "Kırılım tespit edilemedi!"
    assert new_leverage <= 2.2001, "Kaldıraç tavanı aşıldı!"

    # -------------------------------------------------------------------------
    # 2. ADIM: ZAMAN STOPU (TIME STOP) DOĞRULAMASI
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[+] 2. ADIM: ZAMAN STOPU (TIME STOP) TESTİ:")
    print("    * Pozisyon açıldı. Piyasa 12 saat boyunca yatay kalıyor ve kâr 1.0R'a ulaşamıyor...")

    # Açılan pozisyonun durumu
    active_pos = PositionState(
        symbol=symbol,
        entry_price=signal.limit_price,
        initial_stop=signal.stop_price,
        trailing_stop=signal.stop_price,
        lots=signal.target_lots,
        entry_time=datetime.utcnow()
    )

    # 12 bar boyunca fiyatı 314.5 TL'de (küçük kârda) tutan simülasyon döngüsü
    sim_hourly = hourly_df.copy()
    for bar_num in range(1, 13):
        # Yeni bar ekle (Yatay fiyat: 314.5 TL)
        last_time = sim_hourly["timestamp"].iloc[-1] + timedelta(hours=1)
        new_row = pd.DataFrame([{
            "timestamp": last_time,
            "open": 314.2,
            "high": 315.0,
            "low": 313.8,
            "close": 314.4,
            "volume": 80_000.0
        }])
        sim_hourly = pd.concat([sim_hourly, new_row], ignore_index=True)

        exit_signal = engine.evaluate_execution(
            symbol=symbol,
            daily_data=daily_df,
            hourly_data=sim_hourly,
            position_state=active_pos,
            macro_permission=True,
            portfolio_nav=portfolio_nav,
            current_portfolio_leverage=new_leverage
        )

        if exit_signal.action == ExecutionAction.TIME_STOP_EXIT:
            print(f"\n    -> BAR #{bar_num}: ZAMAN STOPU TETİKLENDİ!")
            print(f"    -> Aksiyon : {exit_signal.action.value}")
            print(f"    -> Açıklama: {exit_signal.reason}")
            print(f"    -> Tasfiye Edilen Lot: {exit_signal.target_lots}")
            break
        else:
            print(f"    * Bar #{bar_num}: {exit_signal.reason}")

    assert exit_signal.action == ExecutionAction.TIME_STOP_EXIT, "12 bar sonunda Zaman Stopu çalışmadı!"
    print("\n" + "=" * 80)
    print("  ✓ TÜM GEREKSİNİMLER, B-TARZI KIRILIM, TIRAŞLAMA VE ZAMAN STOPU %100 DOĞRULANDI")
    print("=" * 80)


if __name__ == "__main__":
    run_technical_engine_test()
