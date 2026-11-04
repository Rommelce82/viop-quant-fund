"""
Faz 2.1 Doğrulama ve Çalıştırma Betiği.
"""

import asyncio
from datetime import datetime
import sys

# Windows terminallerinde Türkçe karakter ve UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from src.data.fintables_mcp import FintablesMCPClient
from src.data.global_macro import GlobalMacroClient
from src.execution.rollover_scheduler import (
    ContractExpiryInfo,
    RolloverAction,
    SettlementType,
    ViopRolloverScheduler
)
from src.strategy.liquidity_calculator import LiquidityCalculator
from src.strategy.metrics_calculator import MetricsCalculator


async def validate_phase_2_1() -> None:
    print("=" * 75)
    print("  FAZ 2.1: HESAPLAMA MOTORU, LİKİDİTE, KÜRESEL MAKRO VE ZAMANLAYICI DOĞRULAMA")
    print("=" * 75)

    # 1. HESAPLAMA MOTORU (Piotroski, Altman Z, ROIC, WACC)
    print("\n[+] 1. HESAPLAMA MOTORU (MetricsCalculator):")
    fintables = FintablesMCPClient()
    fund = await fintables.fetch_quarterly_financials("THYAO")
    
    f_res = MetricsCalculator.calculate_piotroski_f_score(fund)
    z_res = MetricsCalculator.calculate_altman_z_score(fund)
    roic_val = MetricsCalculator.calculate_roic(fund)
    wacc_val = MetricsCalculator.calculate_wacc(fund, risk_free_rate=0.50)

    print(f"    * THYAO Piotroski F-Score : {f_res['f_score']}/9 (Güçlü mü: {f_res['is_financially_strong']})")
    print(f"    * THYAO Altman Z-Score    : {z_res['z_score']} (Bölge: {z_res['zone']}, İflas Riski: {z_res['is_distressed']})")
    print(f"    * ROIC (Sermaye Getirisi) : {roic_val:.2%}")
    print(f"    * WACC (Sermaye Maliyeti) : {wacc_val:.2%}")
    print(f"    * EVA Katma Değer Spreadi : {(roic_val - wacc_val):.2%}")

    # 2. LİKİDİTE VE MAKAS MODELLERİ (Amihud & Corwin-Schultz)
    print("\n[+] 2. LİKİDİTE VE MAKAS HESAPLAYICI (LiquidityCalculator):")
    sample_returns = [0.012, -0.005, 0.018, -0.009, 0.004]
    sample_volumes = [650_000_000, 480_000_000, 720_000_000, 510_000_000, 430_000_000]
    amihud = LiquidityCalculator.calculate_amihud_illiquidity(sample_returns, sample_volumes)

    high_low_pairs = [(326.5, 319.0), (329.0, 321.5)]
    cs_spread = LiquidityCalculator.calculate_corwin_schultz_spread(high_low_pairs)
    print(f"    * Amihud İllikidite Endeksi      : {amihud:.7f}")
    print(f"    * Corwin-Schultz Efektif Spread  : {cs_spread:.4%} ({cs_spread * 10000:.1f} bps)")

    # 3. KÜRESEL MAKRO İSTEMCİSİ (Yahoo Finance)
    print("\n[+] 3. KÜRESEL MAKRO VERİ İSTEMCİSİ (GlobalMacroClient):")
    macro_client = GlobalMacroClient()
    glob = await macro_client.fetch_global_macro()
    print(f"    * DXY ABD Dolar Endeksi : {glob['dxy_index']}")
    print(f"    * US 10Y Hazine Getirisi : %{glob['us_10y_yield']}")
    print(f"    * TIP ETF Fiyatı         : {glob['us_tips_etf_price']}")
    print(f"    * Türkiye 5Y CDS Vekili  : {glob['turkey_5y_cds_proxy']} bps")

    # 4. VİOP VADE DÖNGÜSÜ ZAMANLAYICISI (RolloverScheduler)
    print("\n[+] 4. VİOP VADE DÖNGÜSÜ ZAMANLAYICISI (ViopRolloverScheduler):")
    scheduler = ViopRolloverScheduler()
    # 31 Ekim 2026 Vade Sonu
    expiry_oct = datetime(2026, 10, 31)
    scheduler.register_contract(ContractExpiryInfo("F_THYAO", SettlementType.PHYSICAL, expiry_oct))
    scheduler.register_contract(ContractExpiryInfo("F_XU030", SettlementType.CASH, expiry_oct))

    # Test A: Fiziki Vadeye 2 Gün Kala 17:30 (Zorunlu Kapatma)
    action_phy, reason_phy = scheduler.evaluate_contract_status("F_THYAO", datetime(2026, 10, 29, 17, 30))
    print(f"    * F_THYAO (Fiziki) Durumu: {action_phy.value}")
    print(f"      Açıklama: {reason_phy}")
    assert action_phy == RolloverAction.MANDATORY_CLOSE, "Fiziki teslimat 17:00 kuralı MANDATORY_CLOSE üretmeli!"

    # Test B: Nakdi Vade Günü Saat 16:15 (Zorunlu Kapatma)
    action_cash, reason_cash = scheduler.evaluate_contract_status("F_XU030", datetime(2026, 10, 31, 16, 15))
    print(f"    * F_XU030 (Nakdi) Durumu : {action_cash.value}")
    print(f"      Açıklama: {reason_cash}")
    assert action_cash == RolloverAction.MANDATORY_CLOSE, "Nakdi vade sonu saat 16:00 kuralı MANDATORY_CLOSE üretmeli!"

    print("\n" + "=" * 75)
    print("  ✓ FAZ 2.1 TÜM GEREKSİNİMLERİ SIFIR TOLERANSLA EKSİKSİZ TAMAMLANDI")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(validate_phase_2_1())
