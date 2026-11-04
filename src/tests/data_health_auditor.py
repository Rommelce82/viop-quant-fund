"""
Veri Sağlığı ve Anayasa Kapasite Denetçisi (data_health_auditor.py).

Bu denetim betiği;
v4.0 Anayasalarının talep ettiği kritik veri noktaları ile mevcut canlı MCP ve API hatlarının
(Fintables PRO MCP, TCMB resmi kur/faiz servisi, Yahoo Finance küresel makro)
gerçek kapasitesini tek tek test eder.

Checklist:
1. Kademe 1: Fintables Günlük ve Saatlik verilerde open_interest (Açık Pozisyon Sayısı) var mı?
2. Kademe 2 (Banka): Fintables bilançolarından SYR ve Çekirdek Sermaye rasyoları doğrudan çekilebiliyor mu?
3. Kademe 2 (Banka): Fintables bilançolarından Çeyreklik Net Faiz Marjı (NIM) hesaplanabiliyor mu?
4. Kademe 3: Vadeli Fiyat ile Spot Fiyat canlı eşleştirilip Zımni Getiri (IRR) hesaplanabiliyor mu?
5. Makro: TCMB Politika Faizi, USD/TRY, DXY, US10Y ve CDS vekili canlı çekilebiliyor mu?

Çıktı Formatı: [BAŞARILI], [EKSİK - YEDEK PLAN GEREKLİ] veya [HATA].
"""

import asyncio
from datetime import datetime
import json
import logging
import sys
from typing import Dict, List, Optional, Tuple

# Windows UTF-8 desteği
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.data.fintables_mcp import FintablesMCPClient
from src.data.global_macro import GlobalMacroClient
from src.data.tcmb_mcp import TCMBMCPClient

logging.basicConfig(level=logging.ERROR)


class DataHealthAuditor:
    """
    VİOP v4.0 Anayasa Veri Sağlığı ve Kapasite Denetçisi.
    """

    def __init__(self) -> None:
        self.fintables = FintablesMCPClient()
        self.tcmb = TCMBMCPClient()
        self.macro_client = GlobalMacroClient()
        self.audit_results: List[Dict[str, str]] = []

    def _record(self, item: str, status: str, details: str, fallback_plan: str = "Yok") -> None:
        """Denetim sonucunu listeye ekler."""
        self.audit_results.append({
            "item": item,
            "status": status,
            "details": details,
            "fallback_plan": fallback_plan
        })

    async def audit_open_interest(self) -> None:
        """1. DENETİM: Açık Pozisyon Sayısı (open_interest) Kontrolü."""
        print("\n[+] 1. AÇIK POZİSYON SAYISI (OPEN_INTEREST) DENETLENİYOR...")
        try:
            # Saatlik kontrol
            res_hourly = await self.fintables.call_tool(
                "veri_sorgula",
                {"sql": "SELECT * FROM mumlar_saatlik_gh LIMIT 1;", "purpose": "check hourly columns"}
            )
            txt_h = res_hourly.get("content", [{}])[0].get("text", "")
            has_oi_hourly = "open_interest" in txt_h or "acik_pozisyon" in txt_h

            # Günlük kontrol
            res_daily = await self.fintables.call_tool(
                "veri_sorgula",
                {"sql": "SELECT * FROM mumlar_gunluk_gh LIMIT 1;", "purpose": "check daily columns"}
            )
            txt_d = res_daily.get("content", [{}])[0].get("text", "")
            has_oi_daily = "open_interest" in txt_d or "acik_pozisyon" in txt_d

            if has_oi_daily:
                self._record(
                    "Kademe 1: Açık Pozisyon Sayısı (Günlük)",
                    "[BAŞARILI]",
                    "Günlük mum tablosunda açık pozisyon verisi mevcut."
                )
            else:
                self._record(
                    "Kademe 1: Açık Pozisyon Sayısı (Günlük & Saatlik)",
                    "[EKSİK - YEDEK PLAN GEREKLİ]",
                    "Fintables OHLCV tablolarında ('mumlar_gunluk_gh' ve 'mumlar_saatlik_gh') open_interest kolonu yer almıyor. Sadece işlem adedi ve hacim var.",
                    fallback_plan="Kademe 1 likidite filtrelerinde ve kırılımlarda; Açık Pozisyon eşiği yerine 20 Günlük Hacim ve Hacim Patlaması (Volume >= 1.8 * SMA20) kuralı kullanılacaktır."
                )
        except Exception as exc:
            self._record("Kademe 1: Açık Pozisyon Sayısı", "[HATA]", str(exc))

    async def audit_bank_capital_ratios(self) -> None:
        """2. DENETİM: Bankalar için SYR ve Çekirdek Sermaye Kontrolü."""
        print("\n[+] 2. BANKA SERMAYE YETERLİLİK RASYOLARI (SYR & ÇEKİRDEK) DENETLENİYOR...")
        try:
            sql = """
            SELECT DISTINCT oran, kategori, deger 
            FROM hisse_finansal_tablolari_finansal_oranlari 
            WHERE hisse_senedi_kodu = 'AKBNK' 
              AND (oran LIKE '%Sermaye Yeterlilik%' OR oran LIKE '%SYR%' OR oran LIKE '%Çekirdek%' OR oran LIKE '%Tier%')
            LIMIT 5;
            """
            res = await self.fintables.call_tool("veri_sorgula", {"sql": sql, "purpose": "AKBNK SYR query"})
            txt = res.get("content", [{}])[0].get("text", "")
            parsed = json.loads(txt) if txt.startswith("{") else {}
            row_count = parsed.get("row_count", 0)

            if row_count > 0:
                self._record(
                    "Kademe 2 (Banka): SYR ve Çekirdek Sermaye",
                    "[BAŞARILI]",
                    f"Banka oran tablosunda {row_count} adet sermaye rasyosu bulundu."
                )
            else:
                self._record(
                    "Kademe 2 (Banka): SYR ve Çekirdek Sermaye",
                    "[EKSİK - YEDEK PLAN GEREKLİ]",
                    "Fintables 'finansal_oranlari' tablosunda banka SYR ve Çekirdek Sermaye rasyoları doğrudan yer almıyor (BDDK dipnot kalemidir).",
                    fallback_plan="Banka bilanço kalemlerinden 'Özkaynaklar / Toplam Varlıklar' kaldıracı proxy olarak kullanılacak veya BIST Banka Endeksi (XBANK) trend teyidi devreye alınacaktır."
                )
        except Exception as exc:
            self._record("Kademe 2 (Banka): SYR ve Çekirdek Sermaye", "[HATA]", str(exc))

    async def audit_bank_nim_calculation(self) -> None:
        """3. DENETİM: Bankalar için Net Faiz Marjı (NIM) Hesaplanabilirliği."""
        print("\n[+] 3. BANKA NET FAİZ MARJI (NIM) HESAPLANABİLİRLİĞİ DENETLENİYOR...")
        try:
            sql = """
            SELECT 
                f.yil, f.ay,
                nfg.try_ceyreklik as net_faiz_geliri_ceyreklik,
                fa.try_donemsel as krediler
            FROM hisse_finansal_tablolari f
            JOIN hisse_finansal_tablolari_gelir_tablosu_kalemleri nfg
                ON nfg.hisse_senedi_kodu = f.hisse_senedi_kodu AND nfg.yil = f.yil AND nfg.ay = f.ay 
                AND nfg.kalem LIKE '%NET FA%Z GEL%R%'
            JOIN hisse_finansal_tablolari_bilanco_kalemleri fa
                ON fa.hisse_senedi_kodu = f.hisse_senedi_kodu AND fa.yil = f.yil AND fa.ay = f.ay 
                AND fa.kalem = 'Krediler'
            WHERE f.hisse_senedi_kodu = 'AKBNK'
            ORDER BY f.yil DESC, f.ay DESC
            LIMIT 2;
            """
            res = await self.fintables.call_tool("veri_sorgula", {"sql": sql, "purpose": "AKBNK NIM test"})
            txt = res.get("content", [{}])[0].get("text", "")
            parsed = json.loads(txt) if txt.startswith("{") else {}
            table_md = parsed.get("table", "")
            rows = self.fintables._parse_markdown_table(table_md)

            if len(rows) >= 2:
                q1_nfg = float(rows[0]["net_faiz_geliri_ceyreklik"])
                q1_fa = float(rows[0]["krediler"])
                q2_nfg = float(rows[1]["net_faiz_geliri_ceyreklik"])
                q2_fa = float(rows[1]["krediler"])

                nim_q1 = q1_nfg / q1_fa
                nim_q2 = q2_nfg / q2_fa
                delta_nim = nim_q1 - nim_q2

                self._record(
                    "Kademe 2 (Banka): Çeyreklik NIM Değişimi",
                    "[BAŞARILI]",
                    f"Net Faiz Geliri ve Kredi büyüklükleri canlı çekildi. Çeyreklik NIM: {nim_q1:.2%}, Önceki: {nim_q2:.2%}, Delta NIM: {delta_nim:+.2%}"
                )
            else:
                self._record(
                    "Kademe 2 (Banka): Çeyreklik NIM Değişimi",
                    "[EKSİK - YEDEK PLAN GEREKLİ]",
                    "En az 2 çeyreklik banka gelir tablosu kalemi bulunamadı.",
                    fallback_plan="Banka Net Kar Büyümesi proxy olarak kullanılmalıdır."
                )
        except Exception as exc:
            self._record("Kademe 2 (Banka): Çeyreklik NIM Değişimi", "[HATA]", str(exc))

    async def audit_cost_of_carry_irr(self) -> None:
        """4. DENETİM: Vadeli ve Spot Fiyat ile Zımni Getiri (IRR) Hesabı."""
        print("\n[+] 4. TAŞIMA MALİYETİ VE ZIMNİ GETİRİ (IRR) DENETLENİYOR...")
        try:
            sql = """
            SELECT 
                f.kod as vadeli_kod, f.kapanis as vadeli_fiyat, f.zaman_utc as vadeli_zaman,
                s.son_fiyat as spot_fiyat, s.son_fiyat_zaman_utc as spot_zaman
            FROM mumlar_gunluk_gh f
            CROSS JOIN hisse_senetleri s
            WHERE f.kod = 'F_THYAO1026' AND s.hisse_senedi_kodu = 'THYAO'
            ORDER BY f.zaman_utc DESC
            LIMIT 1;
            """
            res = await self.fintables.call_tool("veri_sorgula", {"sql": sql, "purpose": "THYAO IRR test"})
            txt = res.get("content", [{}])[0].get("text", "")
            parsed = json.loads(txt) if txt.startswith("{") else {}
            rows = self.fintables._parse_markdown_table(parsed.get("table", ""))

            if rows:
                r = rows[0]
                vadeli_fiyat = float(r["vadeli_fiyat"])
                spot_fiyat = float(r["spot_fiyat"])
                days_to_expiry = 19  # Ekim 2026 sonuna kalan gün vekili
                
                # Zımni Getiri (Annualized Implied Rate) = ((Vadeli / Spot) - 1) * (365 / Gün)
                basis_pct = (vadeli_fiyat / spot_fiyat) - 1.0
                annualized_irr = basis_pct * (365.0 / max(1, days_to_expiry))

                self._record(
                    "Kademe 3: Taşıma Maliyeti ve Zımni Getiri (IRR)",
                    "[BAŞARILI]",
                    f"Canlı Vadeli ({r['vadeli_kod']} = {vadeli_fiyat} TL) ve Spot (THYAO = {spot_fiyat} TL) eşleşti. Yıllıklandırılmış Zımni Getiri (IRR): %{annualized_irr * 100:.2f}"
                )
            else:
                self._record(
                    "Kademe 3: Taşıma Maliyeti ve Zımni Getiri (IRR)",
                    "[EKSİK - YEDEK PLAN GEREKLİ]",
                    "Vadeli kontrat kodu ve spot fiyat tablosu eşleştirilemedi.",
                    fallback_plan="TCMB repo faizi doğrudan teorik vadeli fiyat hesaplayıcıda (Cost of Carry) kullanılmalıdır."
                )
        except Exception as exc:
            self._record("Kademe 3: Taşıma Maliyeti ve Zımni Getiri (IRR)", "[HATA]", str(exc))

    async def audit_macro_feed(self) -> None:
        """5. DENETİM: TCMB ve yfinance Küresel Makro Veri Akışı."""
        print("\n[+] 5. MAKRO VE KÜRESEL GÖSTERGELER (TCMB & YAHOO FINANCE) DENETLENİYOR...")
        try:
            policy_rate = await self.tcmb.fetch_policy_rate()
            fx = await self.tcmb.fetch_fx_rates()
            glob = await self.macro_client.fetch_global_macro()

            self._record(
                "Makro Veri Akışı (TCMB & Küresel)",
                "[BAŞARILI]",
                f"TCMB Politika Faizi: %{policy_rate:.2f}, USD/TRY: {fx.get('USD_TRY')}, DXY: {glob.get('dxy_index')}, US10Y: %{glob.get('us_10y_yield')}, CDS Vekili: {glob.get('turkey_5y_cds_proxy')} bps"
            )
        except Exception as exc:
            self._record("Makro Veri Akışı (TCMB & Küresel)", "[HATA]", str(exc))

    async def run_audit(self) -> None:
        """Tüm denetimleri sırayla çalıştırır ve rapor basar."""
        print("=" * 80)
        print("  VİOP v4.0 ANAYASAL VERİ SAĞLIĞI VE KAPASİTE DENETİMİ (LIVE AUDIT)")
        print("=" * 80)

        await self.audit_open_interest()
        await self.audit_bank_capital_ratios()
        await self.audit_bank_nim_calculation()
        await self.audit_cost_of_carry_irr()
        await self.audit_macro_feed()

        print("\n" + "=" * 80)
        print("  DENETİM CHECKLIST RAPORU (DATA HEALTH & GAP SUMMARY)")
        print("=" * 80)

        for idx, res in enumerate(self.audit_results, 1):
            print(f"\n[{idx}] {res['item']}")
            print(f"    DURUM        : {res['status']}")
            print(f"    DETAY        : {res['details']}")
            if res["status"] != "[BAŞARILI]":
                print(f"    YEDEK PLAN   : {res['fallback_plan']}")

        print("\n" + "=" * 80)
        print("  ✓ TÜM DENETİM ADIMLARI TAMAMLANDI")
        print("=" * 80)


if __name__ == "__main__":
    auditor = DataHealthAuditor()
    asyncio.run(auditor.run_audit())
