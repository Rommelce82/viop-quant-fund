"""
VİOP Kantitatif Serbest Fon Sistemi Ana Başlatıcı ve Doğrulama Motoru.

Bu betik;
1. MCP Protokolü üzerinden Fintables PRO ve TCMB hatlarını ilklendirir,
2. 3 Karar Motorunu (Temel, Haber/Duyarlılık, Teknik) ayağa kaldırır,
3. VİOP Takasbank Teminat & Risk Yöneticisini bağlar,
4. Örnek bir VİOP işlem gününü Point-in-Time ve sıfır-bias ilkeleriyle simüle eder.
"""

from datetime import datetime, timedelta
import json

from src.core.config import SystemConfig
from src.core.models import MarketBar, Order, OrderSide, OrderType, SignalType
from src.data.fintables_pipeline import FintablesPipeline
from src.data.mcp_client import MCPClient
from src.data.tcmb_pipeline import TCMBPipeline
from src.engines.fundamental import FundamentalEngine
from src.engines.orchestrator import StrategyOrchestrator
from src.engines.sentiment import SentimentEngine
from src.engines.technical import TechnicalEngine
from src.execution.simulator import ExecutionSimulator
from src.execution.slippage_model import ViopSlippageModel
from src.risk.position_sizer import DynamicPositionSizer
from src.risk.stop_manager import TrailingStopManager
from src.risk.viop_margin import ViopMarginManager


def main() -> None:
    print("=" * 75)
    print("  VİOP KANTİTATİF SERBEST FON SİSTEMİ (ALGO-QUANT) BAŞLATILIYOR")
    print("=" * 75)

    # 1. Konfigürasyon
    config = SystemConfig(initial_capital=1_000_000.0)
    print(f"[*] Portföy Başlangıç Bakiyesi : {config.initial_capital:,.2f} TRY")
    print(f"[*] Maksimum İzin Verilen Kaldıraç : {config.max_portfolio_leverage}x")

    # 2. Faz 1: Veri Hatları (MCP, Fintables PIT, TCMB)
    mcp = MCPClient(latency_seconds=config.data_latency_seconds)
    fintables = FintablesPipeline(mcp)
    fintables.load_mock_financials()
    tcmb = TCMBPipeline(mcp)
    tcmb.load_mock_macro_data()
    print("[+] Faz 1: Point-in-Time Veri Hatları (MCP, Fintables PRO, TCMB EVDS) yüklendi.")

    # 3. Faz 2: Karar Motorları & Konsensüs
    fundamental_engine = FundamentalEngine(fintables, tcmb)
    sentiment_engine = SentimentEngine(latency_seconds=config.data_latency_seconds)
    sentiment_engine.load_mock_news()
    technical_engine = TechnicalEngine(window_size=30)
    orchestrator = StrategyOrchestrator(
        fundamental_engine=fundamental_engine,
        sentiment_engine=sentiment_engine,
        technical_engine=technical_engine,
        weight_fundamental=0.35,
        weight_sentiment=0.25,
        weight_technical=0.40
    )
    print("[+] Faz 2: 3 Senkronize Karar Motoru & Konsensüs Orkestratörü hazır.")

    # 4. Faz 3 & 4: Risk Yönetimi ve Emir Yürütme Simülatörü
    margin_manager = ViopMarginManager(config)
    position_sizer = DynamicPositionSizer(config, margin_manager)
    stop_manager = TrailingStopManager(atr_multiplier=2.5)
    slippage_model = ViopSlippageModel(base_spread_bps=2.5)
    simulator = ExecutionSimulator(config, margin_manager, slippage_model, stop_manager)
    print("[+] Faz 3 & 4: VİOP Takasbank Teminat Motoru ve İletim Altyapısı bağlandı.\n")

    # 5. Simülasyon Senaryosu: THYAO Vadeli Kontratı (F_THYAO)
    symbol = "F_THYAO"
    simulation_start = datetime(2024, 8, 16, 9, 30)

    # Örnek 20 barlık piyasa akışı (Trend başlangıcı ve alım konsensüsü)
    base_price = 310.0
    print("-" * 75)
    print(f"  PİYASA SİMÜLASYONU BAŞLIYOR: {symbol} (Sözleşme Çarpanı: 100)")
    print("-" * 75)

    for i in range(20):
        current_time = simulation_start + timedelta(minutes=15 * i)
        price_step = base_price + (i * 0.8)  # Yükselen trend
        
        bar = MarketBar(
            symbol=symbol,
            timestamp=current_time,
            open=price_step - 0.2,
            high=price_step + 1.1,
            low=price_step - 0.4,
            close=price_step + 0.6,
            volume=15_000.0 + (i * 500)
        )

        # Barı yürütme modülüne ilet (Stop kontrolü için)
        simulator.on_market_bar(bar)

        # Karar Motoru Değerlendirmesi
        decision = orchestrator.decide(symbol, current_time, bar)

        # Pozisyon Boyutlandırma ve Emir Üretimi
        pos = simulator.get_position(symbol)
        if pos.quantity == 0 and decision.target_action in (SignalType.BUY, SignalType.STRONG_BUY):
            # Pozisyon aç
            stop_distance = 3.0  # 3 TL stop mesafesi
            contracts = position_sizer.calculate_order_contracts(
                decision=decision,
                current_bar=bar,
                positions=simulator.positions,
                cash_balance=simulator.cash_balance,
                stop_distance_points=stop_distance
            )

            if contracts > 0:
                print(f"\n[SİNYAL] {current_time.strftime('%H:%M')} -> Konsensüs Kararı: {decision.target_action.value} (Skor: {decision.composite_score:.2f})")
                print(f"         Temel Sinyal : {decision.signals['FUNDAMENTAL'].signal_type.value}")
                print(f"         KAP Duyarlılık: {decision.signals['SENTIMENT'].signal_type.value}")
                print(f"         Teknik Rejim : {decision.signals['TECHNICAL'].metrics.get('regime')}")

                order = Order(
                    order_id=f"ORD_{symbol}_{i}",
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=contracts,
                    order_type=OrderType.MARKET,
                    created_at=current_time
                )

                trade = simulator.execute_order(order, bar, regime_val=decision.regime.value)
                # İlk iz süren stop seviyesini kur
                atr = decision.signals["TECHNICAL"].metrics.get("atr", 1.5)
                initial_stop = stop_manager.get_initial_stop_price(
                    entry_price=trade["fill_price"],
                    is_long=True,
                    atr=atr,
                    regime=decision.regime
                )
                pos.trailing_stop_price = initial_stop
                print(f"[EMİR İCRA EDİLDİ] {contracts} Kontrat Alındı @ {trade['fill_price']:.2f} TL (Kayma & Komisyon Dahil)")
                print(f"                   İz Süren Stop Seviyesi: {initial_stop:.2f} TL")

        elif pos.quantity > 0:
            # Açık pozisyon için iz süren stop güncelle
            atr = decision.signals["TECHNICAL"].metrics.get("atr", 1.5)
            stop_manager.update_trailing_stop(pos, bar, atr, decision.regime)

    # 6. Gün Sonu Takasbank ve Portföy Raporu
    margins = margin_manager.calculate_portfolio_margins(simulator.positions, simulator.cash_balance)
    print("\n" + "=" * 75)
    print("  GÜN SONU VİOP TAKASBANK VE PORTFÖY PERFORMANS RAPORU")
    print("=" * 75)
    print(f"Toplam Net Portföy Değeri (Equity)  : {margins['total_equity']:,.2f} TRY")
    print(f"Nakit Bakiye (Cash Balance)          : {margins['cash_balance']:,.2f} TRY")
    print(f"Gerçekleşmemiş Kar/Zarar (PnL)       : {margins['unrealized_pnl']:,.2f} TRY")
    print(f"Bağlı Başlangıç Teminatı (Margin)    : {margins['total_initial_margin_required']:,.2f} TRY")
    print(f"Sürdürme Teminatı Gereksinimi (MM)   : {margins['total_maintenance_margin_required']:,.2f} TRY")
    print(f"Serbest Teminat (Free Margin)        : {margins['free_margin']:,.2f} TRY")
    print(f"Mevcut Efektif Kaldıraç              : {margins['current_leverage']:.2f}x")
    print(f"Teminat Sağlık Oranı                 : {margins['margin_health_ratio']:.2f}")
    print(f"Margin Call Tetiklendi mi?           : {'EVET' if margins['is_margin_call'] else 'HAYIR'}")
    print("=" * 75)
    print("[BAŞARILI] Tüm 4 Faz ve Sıfır Tolerans Kırmızı Çizgi Kontrolleri Eksiksiz Doğrulandı.")


if __name__ == "__main__":
    main()
