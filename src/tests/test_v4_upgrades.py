"""
Test Suite: VİOP v4.0 Mimarisi İleri Düzey İyileştirmeler.

1. Bilanço Kalkanı (Earnings Blackout Window & Cooling-off Window)
2. Çoklu Broker ve Smart Order Router (SOR) Mimarisi
3. Holding (Kanal A1) ve GYO (Kanal A2) Özel Değerleme Kanalları
"""

from datetime import datetime, timedelta
import pytest

from src.data.schemas import FundamentalData
from src.execution.broker_gateway import (
    FixBrokerGateway,
    OrderAction,
    OrderRequest,
    OrderStatus,
    OrderType,
    RestApiBrokerGateway,
)
from src.execution.smart_order_router import SmartOrderRouter
from src.strategy.earnings_blackout import BlackoutPhase, EarningsBlackoutManager
from src.strategy.fundamental_compass import (
    AssetChannel,
    DirectionalBias,
    FundamentalCompass,
    HoldingMetricsInput,
    MarketMicrostructureInput,
    ReitMetricsInput,
)
from src.strategy.metrics_calculator import MetricsCalculator


# ==============================================================================
# 1. BİLANÇO KALKANI TESTLERİ
# ==============================================================================

def test_earnings_blackout_24h_quarantine():
    """Bilanço açıklandıktan sonraki ilk 24 saat içinde tam blokaj (EARNINGS_BLACKOUT) testi."""
    manager = EarningsBlackoutManager(default_quarantine_hours=24.0)
    compass = FundamentalCompass()
    
    announced_time = datetime(2026, 10, 20, 18, 30, 0)
    pre_atr = 4.0
    manager.register_earnings_announcement(
        symbol="F_THYAO",
        announced_at=announced_time,
        pre_earnings_median_atr20=pre_atr
    )
    
    # Bilanço açıklandıktan 5 saat sonrası (karantina içi)
    current_time = announced_time + timedelta(hours=5)
    current_atr = 5.0
    
    phase, msg = manager.evaluate_blackout_state("F_THYAO", current_time, current_atr)
    assert phase == BlackoutPhase.EARNINGS_BLACKOUT
    
    # Compass entegrasyonu: Bilanço kalkanı aktifken doğrudan NEUTRAL ve 0.0 çarpan dönmeli
    micro = MarketMicrostructureInput(adv_try=100_000_000.0, open_interest_contracts=25_000)
    bias, mult, reason = compass.evaluate_directional_bias(
        channel=AssetChannel.EQUITY_REAL,
        blackout_manager=manager,
        symbol="F_THYAO",
        current_time=current_time,
        current_atr14=current_atr
    )
    assert bias == DirectionalBias.NEUTRAL
    assert mult == 0.0
    assert "EARNINGS_BLACKOUT" in reason


def test_earnings_blackout_cooling_off_and_reentry():
    """24 saat dolduktan sonra ATR yatışma şartı ve kademeli re-entry testi."""
    manager = EarningsBlackoutManager(default_quarantine_hours=24.0)
    announced_time = datetime(2026, 10, 20, 18, 30, 0)
    pre_atr = 4.0  # Tavan = 4.0 * 1.5 = 6.0
    manager.register_earnings_announcement(
        symbol="F_THYAO",
        announced_at=announced_time,
        pre_earnings_median_atr20=pre_atr
    )
    
    # 25 saat geçti (24 saat doldu) AMA volatilite hala yüksek (ATR = 7.5 > 6.0)
    t_after_25h = announced_time + timedelta(hours=25)
    phase, msg = manager.evaluate_blackout_state("F_THYAO", t_after_25h, current_atr14=7.5)
    assert phase == BlackoutPhase.COOLING_OFF
    
    # 30 saat geçti VE volatilite yatıştı (ATR = 4.5 <= 6.0)
    t_after_30h = announced_time + timedelta(hours=30)
    phase_calm, msg_calm = manager.evaluate_blackout_state("F_THYAO", t_after_30h, current_atr14=4.5)
    assert phase_calm == BlackoutPhase.ACTIVE


# ==============================================================================
# 2. ÇOKLU BROKER VE AKILLI EMİR YÖNLENDİRME (SOR) TESTLERİ
# ==============================================================================

def test_smart_order_router_margin_allocation_and_slicing():
    """Büyük emirlerin dilimlenmesi (Iceberg) ve çoklu broker teminat dağılımı testi."""
    broker_a = FixBrokerGateway(
        broker_id="BROKER_A_FIX",
        name="Broker A (Düşük Komisyon)",
        initial_free_margin=2_800_000.0,  # 2.8M / 7000 = 400 kontrat kapasitesi
        commission_rate=0.0002
    )
    broker_b = FixBrokerGateway(
        broker_id="BROKER_B_FIX",
        name="Broker B (Derin Teminat)",
        initial_free_margin=10_000_000.0, # 10M / 7000 = ~1428 kontrat kapasitesi
        commission_rate=0.0004
    )
    broker_a.connect()
    broker_b.connect()
    
    sor = SmartOrderRouter(
        gateways=[broker_a, broker_b],
        large_order_threshold=1000,
        iceberg_slice_size=300,
        margin_per_contract=7000.0
    )
    
    # 1.200 kontratlık büyük kurumsal emir (Iceberg 300'lük 4 dilim)
    summary = sor.route_order(
        symbol="F_THYAO",
        action=OrderAction.BUY,
        lots=1200,
        price=320.0
    )
    
    assert summary.is_fully_executed is True
    assert summary.executed_lots == 1200
    assert summary.remaining_lots == 0
    # İlk ucuz Broker A'ya kapasitesi kadar (400 kontrat) gitti, kalanı Broker B'ye (800 kontrat) yönlendirildi
    assert summary.broker_allocations["BROKER_A_FIX"] == 400
    assert summary.broker_allocations["BROKER_B_FIX"] == 800
    assert len(summary.child_executions) >= 4  # Dilimleme gerçekleşti


def test_smart_order_router_failover_reconciliation():
    """Birincil broker koptuğunda (Disconnect/CoD) ikincil broker'a otomatik devir testi."""
    broker_a = FixBrokerGateway(broker_id="BROKER_A", name="Broker A", initial_free_margin=5_000_000.0)
    broker_b = FixBrokerGateway(broker_id="BROKER_B", name="Broker B", initial_free_margin=5_000_000.0)
    
    # Broker A bağlantısı kapalı (Disconnect durumu)
    broker_a.disconnect()
    broker_b.connect()
    
    sor = SmartOrderRouter(gateways=[broker_a, broker_b])
    
    summary = sor.route_order(
        symbol="F_AKBNK",
        action=OrderAction.BUY,
        lots=100,
        price=60.0
    )
    
    assert summary.is_fully_executed is True
    assert summary.executed_lots == 100
    assert "BROKER_B" in summary.broker_allocations
    assert "BROKER_A" not in summary.broker_allocations


# ==============================================================================
# 3. HOLDİNG (KANAL A1) VE GYO (KANAL A2) TESTLERİ
# ==============================================================================

def test_holding_channel_expensive_discount_rejection():
    """Holding hissesi tarihsel ortalamasına göre +1.5 sigma primliyse LONG reddedilmeli."""
    compass = FundamentalCompass()
    
    # Tarihsel medyan iskonto = -%35 (-0.35), std = 0.05
    # Güncel piyasa değeri = 90M TL, İştirak Portföyü = 100M TL -> Güncel İskonto = -%10 (-0.10)
    # Z-Score = (-0.10 - (-0.35)) / 0.05 = +5.0 sigma (Aşırı primli!)
    expensive_holding = HoldingMetricsInput(
        market_cap_try=90_000_000.0,
        subsidiaries_nav_try=100_000_000.0,
        historical_median_nav_discount=-0.35,
        nav_discount_std=0.05,
        holding_solo_net_debt_try=5_000_000.0,
        subsidiary_dividends_to_holding_try=10_000_000.0,
        holding_financial_interest_expense_try=2_000_000.0
    )
    
    bias, mult, reason = compass.evaluate_directional_bias(
        channel=AssetChannel.EQUITY_HOLDING,
        holding_input=expensive_holding
    )
    assert bias == DirectionalBias.NEUTRAL
    assert mult == 0.0
    assert "primli" in reason


def test_holding_channel_solo_debt_and_long_approval():
    """Holding solo borçluluğu %20 altındaysa ve temettü faizi karşılıyorsa ONLY_LONG onayı."""
    compass = FundamentalCompass()
    
    # İskonto medyanın altında (Z <= -0.5), Solo Borç = %10 (<= %20), Temettü = 15M > Faiz = 5M
    healthy_holding = HoldingMetricsInput(
        market_cap_try=55_000_000.0,
        subsidiaries_nav_try=100_000_000.0,  # İskonto = -%45
        historical_median_nav_discount=-0.35,
        nav_discount_std=0.08,               # Z = (-0.45 - (-0.35)) / 0.08 = -1.25 sigma (Cazip)
        holding_solo_net_debt_try=10_000_000.0, # Solo Borç/Portföy = %10
        subsidiary_dividends_to_holding_try=15_000_000.0,
        holding_financial_interest_expense_try=5_000_000.0
    )
    
    bias, mult, reason = compass.evaluate_directional_bias(
        channel=AssetChannel.EQUITY_HOLDING,
        holding_input=healthy_holding
    )
    assert bias == DirectionalBias.ONLY_LONG
    assert mult == 1.0


def test_reit_channel_revaluation_distortion_fixed():
    """GYO'da gayrimenkul değerleme kazancı net kârı şişirse dahi FFO negatifse SHORT olmalı."""
    compass = FundamentalCompass()
    
    # Şirket kağıt üstünde 100M TL net kâr açıklamış fakat bunun 110M TL'si nakit olmayan değerleme kazancı!
    # FFO = 100M - 110M + 2M = -8M TL (Operasyonel nakit üretmiyor!)
    distorted_reit = ReitMetricsInput(
        net_profit_try=100_000_000.0,
        revaluation_gains_try=110_000_000.0,
        depreciation_try=2_000_000.0,
        market_price_try=15.0,
        nav_per_share_try=25.0,
        total_real_estate_portfolio_val_try=500_000_000.0,
        net_debt_try=100_000_000.0
    )
    
    bias, mult, reason = compass.evaluate_directional_bias(
        channel=AssetChannel.EQUITY_REIT,
        reit_input=distorted_reit
    )
    # Hatalı Tahakkuk Anomalisi yerine gerçek FFO analiziyle ONLY_SHORT kararı verilmeli!
    assert bias == DirectionalBias.ONLY_SHORT
    assert mult == 1.0
    assert "Negatif FFO" in reason


def test_reit_channel_healthy_long_approval():
    """GYO'da pozitif FFO, en az %20 ekspertiz iskontosu ve güvenli borçluluk ile ONLY_LONG onayı."""
    compass = FundamentalCompass()
    
    # Net Kâr 50M, Değerleme 20M, Amortisman 5M -> FFO = 35M TL > 0
    # Piyasa Fiyatı = 14 TL, BPD = 20 TL -> Fiyat/BPD = 0.70 (%30 ekspertiz iskontosu)
    # Net Borç = 80M TL / Toplam Portföy = 400M TL -> Kaldıraç = %20 <= %40
    healthy_reit = ReitMetricsInput(
        net_profit_try=50_000_000.0,
        revaluation_gains_try=20_000_000.0,
        depreciation_try=5_000_000.0,
        market_price_try=14.0,
        nav_per_share_try=20.0,
        total_real_estate_portfolio_val_try=400_000_000.0,
        net_debt_try=80_000_000.0
    )
    
    bias, mult, reason = compass.evaluate_directional_bias(
        channel=AssetChannel.EQUITY_REIT,
        reit_input=healthy_reit
    )
    assert bias == DirectionalBias.ONLY_LONG
    assert mult == 1.0
    assert "ONLY_LONG" in reason
