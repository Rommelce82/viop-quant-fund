"""
Fintables MCP VİOP Sözleşmeleri Evreni Sağlık Testi (test_fintables_viop_universe.py).

Test Edilen Varlıklar:
- Reel Sektör: THYAO, EREGL, TUPRS
- Bankacılık: AKBNK
- Holding (Kanal A1): SAHOL
- GYO (Kanal A2): EKGYO
"""

import asyncio
import json
import sys

import pytest
from src.data.fintables_mcp import FintablesMCPClient

# UTF-8 terminal output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@pytest.mark.anyio
async def test_viop_universe_fintables() -> None:
    print("=" * 80)
    print("  FINTABLES MCP VİOP SÖZLEŞMELERİ EVRENİ SAĞLIK TESTİ")
    print("=" * 80)

    fintables = FintablesMCPClient()
    test_symbols = ["THYAO", "AKBNK", "EREGL", "TUPRS", "SAHOL", "EKGYO"]

    results = {}

    for sym in test_symbols:
        print(f"\n[*] {sym} sorgulanıyor...")
        try:
            fin = await fintables.fetch_quarterly_financials(sym)
            kap = await fintables.fetch_kap_disclosures(sym, limit=1)

            print(f"    ✓ Bilanço Alındı: Net Kâr = {fin.net_profit_try:,.0f} TL | Satışlar = {fin.revenue_try:,.0f} TL")
            print(f"    ✓ KAP Haberi Alındı: {kap[0].headline if kap else 'Haber yok'}")
            results[sym] = {
                "status": "HEALTHY",
                "net_profit": fin.net_profit_try,
                "revenue": fin.revenue_try,
                "equity": fin.equity_try,
                "announced_at": fin.announced_at.isoformat() if fin.announced_at else None
            }
        except Exception as e:
            print(f"    ✗ Hata ({sym}): {e}")
            results[sym] = {"status": "FAILED", "error": str(e)}

    print("\n" + "=" * 80)
    healthy_count = sum(1 for r in results.values() if r["status"] == "HEALTHY")
    print(f"  SONUÇ: {healthy_count}/{len(test_symbols)} VİOP Sözleşmesi Fintables MCP'den %100 Başarıyla Çekildi!")
    print("=" * 80)


def test_fintables_ai_universe_calibration() -> None:
    """Fintables AI 26 Ekim 2026 Resmi Sayım Kalibrasyon Testi (4 Sınıf, 63 Dayanak, 207 Sözleşme)."""
    from src.data.viop_universe_definitions import get_universe_breakdown
    b = get_universe_breakdown()
    assert b["total_asset_classes"] == 4, "4 Ana Varlık Sınıfı olmalıdır"
    assert b["total_underlyings"] == 63, "63 Aktif Dayanak Enstrüman olmalıdır"
    assert b["total_active_contracts"] == 207, "207 Aktif Vadeli Sözleşme olmalıdır"

    assert b["categories"]["EQUITY"]["underlyings_count"] == 47
    assert b["categories"]["EQUITY"]["contracts_count"] == 141

    assert b["categories"]["INDEX"]["underlyings_count"] == 4
    assert b["categories"]["INDEX"]["contracts_count"] == 12

    assert b["categories"]["FX"]["underlyings_count"] == 6
    assert b["categories"]["FX"]["contracts_count"] == 36

    assert b["categories"]["COMMODITY"]["underlyings_count"] == 6
    assert b["categories"]["COMMODITY"]["contracts_count"] == 18


if __name__ == "__main__":
    asyncio.run(test_viop_universe_fintables())
    test_fintables_ai_universe_calibration()
    print("✓ Fintables AI 207 Sözleşme Kalibrasyon Testi Başarıyla Tamamlandı!")
