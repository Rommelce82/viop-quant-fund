"""
Canlı Entegrasyon Testi ve Bağlantı Kanıtı (test_mcp_live.py).

Bu test betiği;
1. Canlı Fintables PRO MCP sunucusuna bağlanarak THYAO çeyreklik finansal tablosunu
   ve en son 3 KAP bildirimini çeker,
2. TCMB resmi servisinden güncel politika faizini ve USD/TRY kurunu çeker,
3. Verilerin katı Pydantic şemalarından (FundamentalData, KapNews, MacroData)
   başarıyla geçtiğini model_dump_json() ile terminale döker.
4. Sıfır mock toleransı: Herhangi bir hata oluşursa gizlenmez, doğrudan Exception patlatır.
"""

import asyncio
import json
import sys

from src.data.fintables_mcp import FintablesMCPClient
from src.data.schemas import FundamentalData, KapNews, MacroData
from src.data.tcmb_mcp import TCMBMCPClient

# Windows terminali UTF-8 yapılandırması
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


async def run_live_integration_test() -> None:
    print("=" * 80)
    print("  CANLI MCP ENTEGRASYON VE BAĞLANTI KANITI TESTİ (ZERO MOCK)")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # TEST 1: FINTABLES PRO CANLI MCP ENTEGRASYONU
    # -------------------------------------------------------------------------
    print("\n[+] 1. Fintables PRO Canlı MCP İstemcisi Başlatılıyor...")
    fintables = FintablesMCPClient()
    print(f"    - MCP Uç Noktası: {fintables.endpoint}")
    print(f"    - Bearer Token  : {fintables.token[:15]}...{fintables.token[-10:]} (Doğrulandı)")

    symbol = "THYAO"
    print(f"\n[+] 1.A. {symbol} İçin Çeyreklik Finansal Tablo ve Çarpanlar Çekiliyor...")
    fundamental_record: FundamentalData = await fintables.fetch_quarterly_financials(symbol=symbol)
    
    print("    ✓ Pydantic Doğrulaması Başarılı! JSON Çıktısı:")
    print(json.dumps(json.loads(fundamental_record.model_dump_json()), indent=2, ensure_ascii=False))

    # Kritik Point-in-Time Alanı Kontrolü
    assert fundamental_record.announced_at is not None, "announced_at alanı boş olamaz!"
    assert fundamental_record.as_of_date is not None, "as_of_date alanı boş olamaz!"
    print(f"\n    -> POINT-IN-TIME TEYİDİ: Bilanço Dönemi: {fundamental_record.as_of_date.strftime('%Y-%m-%d')} | KAP İlanı: {fundamental_record.announced_at.isoformat()}")

    print(f"\n[+] 1.B. {symbol} İçin Son 3 Canlı KAP Haberi Çekiliyor...")
    kap_news_list = await fintables.fetch_kap_disclosures(symbol=symbol, limit=3)
    assert len(kap_news_list) >= 1, "En az 1 adet canlı KAP haberi dönmeliydi!"

    print(f"    ✓ {len(kap_news_list)} Adet Canlı KAP Haberi Çekildi ve Pydantic Doğrulamasından Geçti:")
    for idx, news in enumerate(kap_news_list, 1):
        print(f"\n    --- KAP Haberi #{idx} ---")
        print(json.dumps(json.loads(news.model_dump_json()), indent=2, ensure_ascii=False))
        assert news.announced_at is not None, "KAP haberinde announced_at eksik!"

    # -------------------------------------------------------------------------
    # TEST 2: TCMB CANLI MAKRO VE DÖVİZ KURU ENTEGRASYONU
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[+] 2. TCMB Canlı Servis İstemcisi Başlatılıyor...")
    tcmb = TCMBMCPClient()

    print("[+] 2.A. Güncel TCMB Politika Faizi Çekiliyor...")
    policy_rate = await tcmb.fetch_policy_rate()
    print(f"    ✓ TCMB Politika Faizi: %{policy_rate:.2f}")

    print("\n[+] 2.B. TCMB Canlı today.xml Servisinden Döviz Kurları Çekiliyor...")
    fx_rates = await tcmb.fetch_fx_rates()
    print(f"    ✓ Canlı Kurlar: USD/TRY = {fx_rates.get('USD_TRY')}, EUR/TRY = {fx_rates.get('EUR_TRY')}")

    print("\n[+] 2.C. TCMB MacroData Pydantic Nesnesi Doğrulanıyor...")
    macro_state: MacroData = await tcmb.fetch_macro_state()
    print(json.dumps(json.loads(macro_state.model_dump_json()), indent=2, ensure_ascii=False))
    
    assert macro_state.usd_try > 0.0, "USD/TRY kuru pozitif olmalıdır!"
    assert macro_state.announced_at is not None, "TCMB verisinde announced_at eksik olamaz!"

    print("\n" + "=" * 80)
    print("  ✓ TÜM ENTEGRASYON TESTLERİ CANLI VE SIFIR MOCK İLE %100 BAŞARILI!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_live_integration_test())
