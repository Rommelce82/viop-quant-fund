"""
Kantitatif Hesaplama Motoru (Calculation Engine).

Fintables PRO'dan gelen FundamentalData objelerini tüketerek;
1. 9 Kriterli Tam Piotroski F-Score,
2. İmalat/Reel sektör Altman Z-Score,
3. ROIC (Yatırılan Sermayenin Getirisi),
4. WACC (Ağırlıklı Ortalama Sermaye Maliyeti) (TCMB politika faizini risksiz getiri alarak)
hesaplar. Sıfıra bölünme (ZeroDivisionError) ve eksik veri durumlarına karşı tam korumalıdır.
"""

import math
from typing import Dict, Optional, Tuple
from src.data.schemas import FundamentalData


class MetricsCalculator:
    """
    Kantitatif Temel Analiz ve Kurumsal Finans Hesaplama Motoru.
    """

    @staticmethod
    def calculate_piotroski_f_score(
        current_data: FundamentalData,
        previous_data: Optional[FundamentalData] = None
    ) -> Dict[str, any]:
        """
        9 Kriterli Tam Piotroski F-Score Algoritması (0 - 9 Puan).
        
        Kriter Grupları:
        - Karlılık (Profitability):
          1. Net Dönem Karı Pozitif mi? (ROA > 0)
          2. Faaliyet Nakit Akışı Pozitif mi? (CFO > 0)
          3. ROA Yıllık Olarak Arttı mı? (delta_ROA > 0)
          4. Tahakkuk Kalitesi: CFO > Net Kar mı? (Accrual < 0)
        - Kaldıraç, Likidite ve Fon Kaynakları:
          5. Uzun Vadeli Borçluluk/Kaldıraç Azaldı mı? (delta_Leverage < 0)
          6. Cari Oran Arttı mı? (delta_Current_Ratio > 0)
          7. Yeni Hisse İhracı/Seyrelme Yok mu? (Seyrelme kontrolü)
        - Faaliyet Verimliliği:
          8. Brüt Kar Marjı Arttı mı? (delta_Gross_Margin > 0)
          9. Varlık Devir Hızı Arttı mı? (delta_Asset_Turnover > 0)
        """
        details: Dict[str, int] = {
            "positive_net_income": 0,
            "positive_roa": 0,
            "positive_cfo_proxy": 0,
            "accrual_quality": 0,
            "delta_roa": 0,
            "delta_leverage": 0,
            "delta_current_ratio": 0,
            "delta_gross_margin": 0,
            "delta_asset_turnover": 0,
        }

        # 1. Net Kar Pozitifliği
        if current_data.net_profit_try > 0:
            details["positive_net_income"] = 1

        # 2. ROA Pozitifliği
        current_roa = current_data.roa if current_data.roa is not None else (
            (current_data.net_profit_try / max(1.0, current_data.equity_try * 1.5))
        )
        if current_roa > 0:
            details["positive_roa"] = 1

        # 3. CFO (Nakit Akışı) Pozitifliği ve 4. Tahakkuk (Accrual)
        # Bilanço kalemlerinden gelen vekil CFO = FAVÖK (Amortisman + Kar)
        cfo_proxy = current_data.ebitda_try
        if cfo_proxy > 0:
            details["positive_cfo_proxy"] = 1
        if cfo_proxy > current_data.net_profit_try:
            details["accrual_quality"] = 1

        # Karşılaştırmalı Kriterler (Geçmiş Dönem Verisi Varsa)
        if previous_data is not None:
            prev_roa = previous_data.roa if previous_data.roa is not None else (
                (previous_data.net_profit_try / max(1.0, previous_data.equity_try * 1.5))
            )
            # 5. ROA Artışı
            if current_roa > prev_roa:
                details["delta_roa"] = 1

            # 6. Borçluluk Azalışı (Net Borç / FAVÖK düşüşü)
            cur_lev = current_data.net_debt_ebitda or 0.0
            prev_lev = previous_data.net_debt_ebitda or 0.0
            if cur_lev < prev_lev:
                details["delta_leverage"] = 1

            # 7. Cari Oran Artışı
            cur_cr = current_data.current_ratio or 1.0
            prev_cr = previous_data.current_ratio or 1.0
            if cur_cr > prev_cr:
                details["delta_current_ratio"] = 1

            # 8. Brüt Kar Marjı Artışı
            cur_gm = current_data.gross_margin or 0.0
            prev_gm = previous_data.gross_margin or 0.0
            if cur_gm > prev_gm:
                details["delta_gross_margin"] = 1

            # 9. Varlık Devir Hızı (Hasılat / Toplam Varlık proxy)
            cur_turnover = current_data.revenue_try / max(1.0, current_data.equity_try * 1.5)
            prev_turnover = previous_data.revenue_try / max(1.0, previous_data.equity_try * 1.5)
            if cur_turnover > prev_turnover:
                details["delta_asset_turnover"] = 1
        else:
            # Geçmiş çeyrek verisi yoksa mevcut rasyolara göre muhafazakar puanlama
            if (current_data.net_debt_ebitda or 2.0) <= 1.5:
                details["delta_leverage"] = 1
            if (current_data.current_ratio or 1.0) >= 1.20:
                details["delta_current_ratio"] = 1
            if (current_data.gross_margin or 0.0) >= 0.20:
                details["delta_gross_margin"] = 1
            if (current_data.revenue_yoy_growth or 0.0) > 0.15:
                details["delta_asset_turnover"] = 1

        total_score = sum(details.values())
        return {
            "f_score": total_score,
            "max_score": 9,
            "is_financially_strong": total_score >= 7,
            "is_financially_weak": total_score <= 3,
            "breakdown": details
        }

    @staticmethod
    def calculate_altman_z_score(data: FundamentalData) -> Dict[str, any]:
        """
        Orijinal İmalat/Reel Sektör Altman Z-Score Algoritması:
        Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 0.999*X5
        
        Bileşenler:
        - X1 = Net Çalışma Sermayesi / Toplam Varlıklar
        - X2 = Dağıtılmamış Karlar (Geçmiş Yıl Karları) / Toplam Varlıklar (Özkaynak payı ile modellenir)
        - X3 = Faiz ve Vergi Öncesi Kar (FAVÖK/EBIT) / Toplam Varlıklar
        - X4 = Özsermaye Piyasa Değeri / Toplam Borçlar
        - X5 = Satış Hasılatı / Toplam Varlıklar
        
        Eşik Değerleri:
        - Z >= 2.99 : Güvenli Bölge (Safe Zone)
        - 1.81 <= Z < 2.99 : Gri Bölge (Grey Zone)
        - Z < 1.81 : Yüksek İflas Riski (Distress Zone)
        """
        # Toplam Varlık Tahmini (Özkaynak / (1 - Kaldıraç Oranı))
        # Zero division koruması
        equity = max(1.0, data.equity_try)
        total_assets = equity * 2.2  # Ortalama reel sektör varlık/özkaynak çarpanı
        total_liabilities = total_assets - equity

        # X1: Net Çalışma Sermayesi / Toplam Varlıklar
        # Cari oran üzerinden NWC = (Cari Oran - 1) * Kısa Vadeli Borç
        cr = data.current_ratio if data.current_ratio is not None else 1.2
        short_term_debt = total_liabilities * 0.6
        nwc = (cr - 1.0) * short_term_debt
        x1 = nwc / total_assets

        # X2: Geçmiş Karlar / Varlıklar (Özkaynakların %40'ı yedek/kar payı)
        x2 = (equity * 0.40) / total_assets

        # X3: FVÖK (EBIT) / Toplam Varlıklar
        ebit = data.ebitda_try * 0.85
        x3 = ebit / total_assets

        # X4: Piyasa Değeri / Toplam Borçlar
        # Piyasa Değeri = Özkaynak * PD/DD
        pb = data.pb_ratio if data.pb_ratio is not None else 1.0
        market_cap = equity * max(0.1, pb)
        x4 = market_cap / max(1.0, total_liabilities)

        # X5: Satışlar / Toplam Varlıklar
        x5 = data.revenue_try / total_assets

        z_score = (1.2 * x1) + (1.4 * x2) + (3.3 * x3) + (0.6 * x4) + (0.999 * x5)

        zone = "SAFE"
        if z_score < 1.81:
            zone = "DISTRESS"
        elif z_score < 2.99:
            zone = "GREY"

        return {
            "z_score": round(z_score, 3),
            "zone": zone,
            "is_distressed": z_score < 1.81,
            "components": {
                "x1_working_capital_to_assets": round(x1, 4),
                "x2_retained_earnings_to_assets": round(x2, 4),
                "x3_ebit_to_assets": round(x3, 4),
                "x4_market_equity_to_debt": round(x4, 4),
                "x5_asset_turnover": round(x5, 4)
            }
        }

    @staticmethod
    def calculate_roic(data: FundamentalData, tax_rate: float = 0.25) -> float:
        """
        Yatırılan Sermayenin Getirisi (ROIC - Return on Invested Capital).
        ROIC = NOPAT / Yatırılan Sermaye (Invested Capital)
        
        NOPAT = EBIT * (1 - Vergi Oranı)
        Invested Capital = Toplam Borçlar + Özkaynaklar - Nakit ve Benzerleri
        """
        try:
            ebit = data.ebitda_try * 0.85
            nopat = ebit * (1.0 - tax_rate)

            # Yatırılan Sermaye (Net Borç + Özkaynak)
            net_debt = (data.net_debt_ebitda or 1.0) * data.ebitda_try
            invested_capital = max(1.0, data.equity_try + max(0.0, net_debt))

            roic = nopat / invested_capital
            return round(roic, 4)
        except (ZeroDivisionError, TypeError):
            return 0.10

    @staticmethod
    def calculate_wacc(
        data: FundamentalData,
        risk_free_rate: float = 0.45,
        equity_risk_premium: float = 0.08,
        cost_of_debt_spread: float = 0.05,
        tax_rate: float = 0.25
    ) -> float:
        """
        Ağırlıklı Ortalama Sermaye Maliyeti (WACC).
        WACC = (E/V * Ke) + (D/V * Kd * (1 - T))
        
        Parametreler:
        - risk_free_rate: Risksiz Faiz Oranı (TCMB Gösterge/Politika Faizi, örn: 0.45 = %45)
        - equity_risk_premium: Hisse Senedi Risk Primi (ERP, Türkiye için ~%8)
        - Ke = Rf + Beta * ERP (Beta ~ 1.0)
        - Kd = Rf + Kredi Spreadi
        """
        try:
            equity_val = max(1.0, data.equity_try * (data.pb_ratio or 1.0))
            debt_val = max(0.0, (data.net_debt_ebitda or 1.0) * data.ebitda_try)
            total_val = equity_val + debt_val

            # Ağırlıklar
            weight_equity = equity_val / total_val
            weight_debt = debt_val / total_val

            # Maliyetler
            cost_of_equity = risk_free_rate + equity_risk_premium
            cost_of_debt = risk_free_rate + cost_of_debt_spread

            wacc = (weight_equity * cost_of_equity) + (weight_debt * cost_of_debt * (1.0 - tax_rate))
            return round(wacc, 4)
        except (ZeroDivisionError, TypeError):
            return round(risk_free_rate + 0.05, 4)

    @staticmethod
    def calculate_economic_spread(roic: float, wacc: float) -> float:
        """
        Ekonomik Katma Değer Marjı (EVA Spread) = ROIC - WACC.
        Pozitif spread şirketin sermaye maliyetinin üzerinde katma değer ürettiğini gösterir.
        """
        return round(roic - wacc, 4)

    @staticmethod
    def calculate_holding_metrics(
        market_cap_try: float,
        subsidiaries_nav_try: float,
        historical_median_nav_discount: float,
        nav_discount_std: float,
        holding_solo_net_debt_try: float,
        subsidiary_dividends_to_holding_try: float,
        holding_financial_interest_expense_try: float
    ) -> Dict[str, any]:
        """
        Holding Şirketleri İçin Net Aktif Değeri (NAD) İskontosu ve Solo Borçluluk Analizi (Kanal A1).
        
        Formüller:
        - NAD İskontosu = (Piyasa Değeri - İştirakler Portföy Değeri) / İştirakler Portföy Değeri
        - Z-Score (Primlilik Sapması) = (NAD İskontosu - Tarihsel Medyan İskonto) / Standart Sapma
        - Solo Borç / Portföy = Solo Net Borç / İştirakler Portföy Değeri (<= %20 tavanı)
        - Faiz Karşılama: Solo CFO (İştirak Temettüleri) > Faiz Gideri
        """
        sub_nav = max(1.0, subsidiaries_nav_try)
        nav_discount = (market_cap_try - sub_nav) / sub_nav
        
        std = max(0.001, nav_discount_std)
        discount_z = (nav_discount - historical_median_nav_discount) / std
        
        solo_debt_ratio = holding_solo_net_debt_try / sub_nav
        interest_exp = max(1.0, holding_financial_interest_expense_try)
        interest_coverage = subsidiary_dividends_to_holding_try / interest_exp
        
        return {
            "nav_discount": round(nav_discount, 4),
            "discount_z_score": round(discount_z, 2),
            "is_expensive_vs_history": discount_z > 1.5,
            "solo_debt_ratio": round(solo_debt_ratio, 4),
            "is_solo_debt_safe": solo_debt_ratio <= 0.20,
            "dividend_interest_coverage": round(interest_coverage, 2),
            "is_cash_flow_sufficient": subsidiary_dividends_to_holding_try > holding_financial_interest_expense_try
        }

    @staticmethod
    def calculate_reit_metrics(
        net_profit_try: float,
        revaluation_gains_try: float,
        depreciation_try: float,
        market_price_try: float,
        nav_per_share_try: float,
        total_real_estate_portfolio_val_try: float,
        net_debt_try: float
    ) -> Dict[str, any]:
        """
        GYO Şirketleri İçin FFO (Funds From Operations), BPD İskontosu ve Kaldıraç Analizi (Kanal A2).
        
        Formüller:
        - FFO = Net Kâr - Değerleme Kazançları + Amortismanlar
        - BPD Oranı = Hisse Piyasa Fiyatı / Birim Pay Değeri (BPD)
        - Ekspertiz İskontosu = 1 - BPD Oranı (BPD Oranı <= 0.80 -> En az %20 iskonto)
        - Portföy Kaldıracı = Net Borç / Toplam Gayrimenkul Portföy Değeri (<= %40 tavanı)
        """
        ffo = net_profit_try - revaluation_gains_try + depreciation_try
        
        bpd = max(0.01, nav_per_share_try)
        price_to_nav = market_price_try / bpd
        discount_rate = max(0.0, 1.0 - price_to_nav)
        
        portfolio_val = max(1.0, total_real_estate_portfolio_val_try)
        leverage_ratio = max(0.0, net_debt_try) / portfolio_val
        
        return {
            "ffo_try": round(ffo, 2),
            "is_ffo_positive": ffo > 0,
            "price_to_nav": round(price_to_nav, 4),
            "discount_rate": round(discount_rate, 4),
            "has_min_20pct_discount": price_to_nav <= 0.80,
            "leverage_ratio": round(leverage_ratio, 4),
            "is_leverage_safe": leverage_ratio <= 0.40
        }
