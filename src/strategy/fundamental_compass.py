"""
Temel Analiz ve Yön Pusulası Anayasası (v4.0).

Rol: Evren Seçimi (Universe Selection) ve Yön Eğilimi (Directional Bias) Belirleyici.
Yetki Sınırı: Sadece ONLY_LONG, ONLY_SHORT veya NEUTRAL kararı üretir.
Risk yönetimi, lot hesabı ve stop-loss yetkisi KESİNLİKLE YOKTUR.

Kademeler:
- KADEME 1: Likidite ve Mikroyapı Filtresi (ADV ve Açık Pozisyon eşikleri)
- KADEME 2: Çok Varlıklı Yön Motoru:
  * Kanal A: Reel Sektör Pay Vadeli (Piotroski, Altman Z, CFO > Net Kar, ROIC > WACC)
  * Kanal B: Banka Pay Vadeli (SYR >= %16, Çekirdek Sermaye >= %12, Çeyreklik NIM Değişimi >= 0)
  * Kanal C: Döviz Vadeli (Zımni Faiz, TLREF, CDS Trendi)
  * Kanal D: Emtia Ons Altın (US 10Y TIPS Trendi, DXY < SMA50)
- KADEME 3: Taşıma Maliyeti (Cost of Carry) Süzgeci:
  * Fahiş Contango Koruması: Zımni Getiri (IRR) > (TCMB Fonlama Faizi + 250 bps) ise ONLY_LONG -> NEUTRAL
  * Derin Backwardation Koruması: IRR < (TCMB Fonlama Faizi - 250 bps) ise ONLY_SHORT -> NEUTRAL
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Tuple
from src.data.schemas import FundamentalData
from src.strategy.earnings_blackout import EarningsBlackoutManager, BlackoutPhase
from src.strategy.metrics_calculator import MetricsCalculator


class DirectionalBias(str, Enum):
    """Temel Yön Eğilimi."""
    ONLY_LONG = "ONLY_LONG"
    ONLY_SHORT = "ONLY_SHORT"
    NEUTRAL = "NEUTRAL"
    BI_DIRECTIONAL = "BI_DIRECTIONAL"  # VİOP çift yönlü işlem izni (Teknik Trende Göre Long veya Short)


class AssetChannel(str, Enum):
    """Varlık Türü Kanalı."""
    EQUITY_REAL = "EQUITY_REAL"        # Reel Sektör Pay Vadeli
    EQUITY_BANK = "EQUITY_BANK"        # Banka Pay Vadeli
    EQUITY_HOLDING = "EQUITY_HOLDING"  # Holding Pay Vadeli (Kanal A1 - NAD & Solo Borç)
    EQUITY_REIT = "EQUITY_REIT"        # GYO Pay Vadeli (Kanal A2 - FFO & BPD İskontosu)
    FX = "FX"                          # Döviz Vadeli (USDTRY)
    COMMODITY = "COMMODITY"            # Emtia (XAUUSD / Ons Altın)
    INDEX = "INDEX"                    # Endeks Vadeli (F_XU030)


@dataclass
class MarketMicrostructureInput:
    """Mikroyapı ve Likidite Girdileri."""
    adv_try: float                 # 20 Günlük Ortalama Günlük İşlem Hacmi (TRY)
    open_interest_contracts: int   # Açık Pozisyon Sayısı (Kontrat)


@dataclass
class CostOfCarryInput:
    """Taşıma Maliyeti ve Getiri Girdileri."""
    implied_irr: float             # Yıllıklandırılmış Zımni Getiri (Örn: 0.525 = %52.5)
    tcmb_funding_rate: float       # TCMB Ağırlıklı Ortalama Fonlama Faizi (Örn: 0.50 = %50)


@dataclass
class BankMetricsInput:
    """Banka Bilanço Girdileri."""
    car_ratio: float               # Sermaye Yeterlilik Rasyosu (SYR) (Örn: 0.17 = %17)
    tier1_ratio: float             # Çekirdek Sermaye Oranı (Örn: 0.13 = %13)
    nim_change_quarterly: float    # Çeyreklik Net Faiz Marjı (NIM) Değişimi (Puan)


@dataclass
class HoldingMetricsInput:
    """Holding Şirketleri İçin Özel Bilanço ve NAD Girdileri (Kanal A1)."""
    market_cap_try: float                           # Holding Güncel Piyasa Değeri (TL)
    subsidiaries_nav_try: float                     # Toplam İştirak Net Aktif Değeri (TL)
    historical_median_nav_discount: float           # Tarihsel Medyan NAD İskontosu (Örn: -0.30 = %30 İskonto)
    nav_discount_std: float                         # Tarihsel NAD İskonto Standart Sapması (Örn: 0.08)
    holding_solo_net_debt_try: float                # Holding Solo Net Borç (TL)
    subsidiary_dividends_to_holding_try: float      # İştiraklerden Holding'e akan nakit temettü (Solo CFO) (TL)
    holding_financial_interest_expense_try: float   # Holding Finansal Borç Faiz Gideri (TL)


@dataclass
class ReitMetricsInput:
    """GYO (Gayrimenkul Yatırım Ortaklığı) İçin Özel Değerleme Girdileri (Kanal A2)."""
    net_profit_try: float                           # Net Dönem Kârı (TL)
    revaluation_gains_try: float                    # Gayrimenkul Değerleme Kazançları (Kayıtlı, Nakit Olmayan) (TL)
    depreciation_try: float                         # Amortisman ve İtfa Payları (TL)
    market_price_try: float                         # Hisse Piyasa Fiyatı (TL)
    nav_per_share_try: float                        # Birim Pay Değeri (BPD / NAV per Share) (TL)
    total_real_estate_portfolio_val_try: float      # Toplam Gayrimenkul Portföy Değeri (Ekspertiz) (TL)
    net_debt_try: float                             # Net Borç (TL)


@dataclass
class MacroTrendsInput:
    """Döviz ve Emtia Makro Trend Girdileri."""
    implied_interest_rate: float   # Döviz Vadeli Zımni Faiz Oranı
    tlref_rate: float              # TLREF Referans Faiz Oranı
    cds_5y_trend: float            # Türkiye 5Y CDS Değişim Eğimi (Pozitif = Yükselen risk, Negatif = İyileşen)
    us_10y_tips_trend: float       # US 10Y TIPS Reel Faiz Trendi (Pozitif / Negatif)
    dxy_current: float             # Güncel DXY Değeri
    dxy_sma_50: float              # DXY 50 Günlük SMA Değeri


class FundamentalCompass:
    """
    VİOP Temel Analiz ve Yön Pusulası (v4.0).
    """

    # KADEME 1 Likidite ve Mikroyapı Eşikleri
    MICROSTRUCTURE_THRESHOLDS = {
        AssetChannel.EQUITY_REAL: {"min_adv": 75_000_000.0, "min_oi": 20_000},
        AssetChannel.EQUITY_BANK: {"min_adv": 75_000_000.0, "min_oi": 20_000},
        AssetChannel.EQUITY_HOLDING: {"min_adv": 75_000_000.0, "min_oi": 20_000},
        AssetChannel.EQUITY_REIT: {"min_adv": 75_000_000.0, "min_oi": 20_000},
        AssetChannel.INDEX: {"min_adv": 500_000_000.0, "min_oi": 100_000},
        AssetChannel.FX: {"min_adv": 100_000_000.0, "min_oi": 30_000},
        AssetChannel.COMMODITY: {"min_adv": 50_000_000.0, "min_oi": 10_000},
    }

    def evaluate_microstructure_filter(
        self,
        channel: AssetChannel,
        micro: MarketMicrostructureInput
    ) -> Tuple[bool, str]:
        """
        KADEME 1: Likidite ve Mikroyapı Filtresi.
        Şartları sağlamayan sözleşmeler işlem evreninden dışlanır (NEUTRAL).
        """
        thresholds = self.MICROSTRUCTURE_THRESHOLDS.get(channel)
        if not thresholds:
            return False, f"{channel.value} için mikroyapı eşiği tanımlı değil."

        if micro.adv_try < thresholds["min_adv"]:
            return False, f"Yetersiz ADV: {micro.adv_try:,.0f} TL < {thresholds['min_adv']:,.0f} TL"

        if micro.open_interest_contracts < thresholds["min_oi"]:
            return False, f"Yetersiz Açık Pozisyon: {micro.open_interest_contracts:,} < {thresholds['min_oi']:,} kontrat"

        return True, "Likidite ve Mikroyapı Onaylandı."

    def evaluate_directional_bias(
        self,
        channel: AssetChannel,
        fundamental_data: Optional[FundamentalData] = None,
        previous_fundamental_data: Optional[FundamentalData] = None,
        bank_input: Optional[BankMetricsInput] = None,
        holding_input: Optional[HoldingMetricsInput] = None,
        reit_input: Optional[ReitMetricsInput] = None,
        macro_input: Optional[MacroTrendsInput] = None,
        tcmb_policy_rate: float = 0.50,
        sector_average_z: Optional[float] = None,
        blackout_manager: Optional[EarningsBlackoutManager] = None,
        symbol: Optional[str] = None,
        current_time: Optional[datetime] = None,
        current_atr14: Optional[float] = None
    ) -> Tuple[DirectionalBias, float, str]:
        """
        KADEME 2: Çok Varlıklı Yön ve Dinamik Bütçe Motoru (Ali Perşembe Doktrini).
        Dönüş: (DirectionalBias, multiplier, rationale)
        Multiplier:
          1.0 = Tier 1 (Güçlü)
          0.5 = Tier 2 (İyileşen / Nötrden Dönüş)
          0.0 = Tier 3 (Distressed / Tam Blokaj)
        """
        # 0. BİLANÇO KALKANI (Earnings Blackout Window & Cooling-off Window)
        if blackout_manager and symbol and current_time:
            atr = current_atr14 if current_atr14 is not None else 1.0
            allowed, phase, blackout_msg = blackout_manager.is_trade_allowed(symbol, current_time, atr)
            if not allowed:
                return DirectionalBias.NEUTRAL, 0.0, f"Bilanço Kalkanı Engeli ({phase.value}): {blackout_msg}"

        # KANAL A: Reel Sektör Pay Vadeli (ve Endeks)
        if channel in (AssetChannel.EQUITY_REAL, AssetChannel.INDEX):
            if channel == AssetChannel.INDEX:
                # Endeks VİOP: Makro ve Trend Motoru Önceliklidir (Çift Yönlü İcra İzni)
                return (
                    DirectionalBias.BI_DIRECTIONAL,
                    1.0,
                    "Kanal A (Endeks): Makro Trend & Çift Yönlü İcra İzni (Tam Bütçe x1.0)."
                )

            if not fundamental_data:
                return DirectionalBias.NEUTRAL, 0.0, "Reel sektör için FundamentalData verisi eksik."

            f_score_res = MetricsCalculator.calculate_piotroski_f_score(
                current_data=fundamental_data,
                previous_data=previous_fundamental_data
            )
            z_score_res = MetricsCalculator.calculate_altman_z_score(fundamental_data)
            roic = MetricsCalculator.calculate_roic(fundamental_data)
            wacc = MetricsCalculator.calculate_wacc(fundamental_data, risk_free_rate=tcmb_policy_rate)

            f_score = f_score_res["f_score"]
            z_score = z_score_res["z_score"]
            cfo_proxy = fundamental_data.ebitda_try
            net_profit = fundamental_data.net_profit_try
            net_debt_ebitda = fundamental_data.net_debt_ebitda or 0.0

            # Delta Z (Momentum / İyileşme İvmesi) Hesabı
            delta_z = 0.0
            if previous_fundamental_data:
                prev_z_res = MetricsCalculator.calculate_altman_z_score(previous_fundamental_data)
                delta_z = round(z_score - prev_z_res["z_score"], 4)
            else:
                # Önceki dönem yoksa cari bilançonun net kar veya ciro büyümesine göre proxy
                delta_z = 0.1 if (fundamental_data.net_income_yoy_growth or 0.0) > 0 else -0.1

            sec_z = sector_average_z if sector_average_z is not None else 2.10

            # Fırsat Odaklı Kalibrasyon: F >= 5 ve Z >= 2.10 veya Delta Z > 0
            is_tier1 = (z_score >= 2.40) or (z_score > sec_z and delta_z > 0.0)
            is_tier2 = (z_score < 2.40) and (delta_z >= 0.0 or f_score >= 5)
            is_tier3 = (z_score < 1.60) and (delta_z < 0.0) and (f_score <= 3)

            # ONLY_SHORT Şartları: F <= 3 OR Net Borç / FAVÖK > 4.5
            if (f_score <= 3 or net_debt_ebitda > 4.5):
                return (
                    DirectionalBias.ONLY_SHORT,
                    1.0,
                    f"Kanal A ONLY_SHORT: F={f_score}/9 <= 3 veya NetBorç/FAVÖK={net_debt_ebitda:.2f} > 4.5"
                )

            # Temel Kriterler LONG için uygun mu? (F >= 5 ve nakit akışı veya ciro büyümesi)
            is_fundamental_long_eligible = (f_score >= 5 and (cfo_proxy > 0 or (fundamental_data.revenue_yoy_growth or 0) > 0.20))

            if is_tier1 and is_fundamental_long_eligible:
                return (
                    DirectionalBias.ONLY_LONG,
                    1.0,
                    f"Kanal A Tier 1 (Tam Bütçe x1.0): F={f_score}, Z={z_score:.2f}, dZ={delta_z:+.2f}, ROIC({roic:.1%})"
                )
            elif is_tier2 and is_fundamental_long_eligible:
                return (
                    DirectionalBias.ONLY_LONG,
                    0.5,
                    f"Kanal A Tier 2 (Yarım Bütçe x0.5 - Ali Perşembe Dinamik İvme): Z={z_score:.2f}, F={f_score}, dZ={delta_z:+.2f}"
                )
            elif is_tier3:
                return (
                    DirectionalBias.NEUTRAL,
                    0.0,
                    f"Kanal A Tier 3 (Tam Blokaj x0.0 - Distressed): Z={z_score:.2f} < 1.60 ve F={f_score} <= 3"
                )

            return (
                DirectionalBias.ONLY_LONG,
                0.5,
                f"Kanal A Esnek İzin: F={f_score}, Z={z_score:.2f}, Çarpan=0.5"
            )

        # KANAL A1: Holding Pay Vadeli (NAD İskontosu ve Solo Borçluluk)
        elif channel == AssetChannel.EQUITY_HOLDING:
            if not holding_input:
                return DirectionalBias.NEUTRAL, 0.0, "Holding için HoldingMetricsInput verisi eksik."

            metrics = MetricsCalculator.calculate_holding_metrics(
                market_cap_try=holding_input.market_cap_try,
                subsidiaries_nav_try=holding_input.subsidiaries_nav_try,
                historical_median_nav_discount=holding_input.historical_median_nav_discount,
                nav_discount_std=holding_input.nav_discount_std,
                holding_solo_net_debt_try=holding_input.holding_solo_net_debt_try,
                subsidiary_dividends_to_holding_try=holding_input.subsidiary_dividends_to_holding_try,
                holding_financial_interest_expense_try=holding_input.holding_financial_interest_expense_try
            )

            # Kural 1: Tarihsel medyan NAD iskontosuna göre +1.5 sigma primliyse LONG yasaklanır
            if metrics["is_expensive_vs_history"]:
                return (
                    DirectionalBias.NEUTRAL,
                    0.0,
                    f"Kanal A1 (Holding) Blokajı: NAD iskontosu tarihsel ortalamaya göre +1.5 sigma primli (Z={metrics['discount_z_score']:.2f} > 1.5). LONG yasak."
                )

            # Kural 2: Solo Net Borç / İştirak Portföy Değeri <= %20
            if not metrics["is_solo_debt_safe"]:
                return (
                    DirectionalBias.ONLY_SHORT,
                    1.0,
                    f"Kanal A1 (Holding) ONLY_SHORT: Solo Net Borç / Portföy ({metrics['solo_debt_ratio']:.1%}) > %20 tavanı."
                )

            # Kural 3: İştirak temettü akışı faiz giderini karşılamıyorsa (Solo CFO <= Faiz Gideri)
            if not metrics["is_cash_flow_sufficient"]:
                return (
                    DirectionalBias.NEUTRAL,
                    0.0,
                    f"Kanal A1 (Holding) Nötr: İştirak temettü akışı faiz giderini karşılamıyor (Karşılama: {metrics['dividend_interest_coverage']:.2f}x)."
                )

            # Tüm şartlar sağlandı -> LONG İzni (İskonto medyanın 0.5 sigma altındaysa Tier 1 x1.0, değilse Tier 2 x0.5)
            multiplier = 1.0 if metrics["discount_z_score"] <= -0.5 else 0.5
            return (
                DirectionalBias.ONLY_LONG,
                multiplier,
                f"Kanal A1 (Holding) ONLY_LONG: NAD İskontosu={metrics['nav_discount']:.1%}, Solo Borç={metrics['solo_debt_ratio']:.1%} <= %20, Faiz Karşılama={metrics['dividend_interest_coverage']:.1f}x (Çarpan: {multiplier})"
            )

        # KANAL A2: GYO (Gayrimenkul Yatırım Ortaklığı) Pay Vadeli (FFO ve BPD İskontosu)
        elif channel == AssetChannel.EQUITY_REIT:
            if not reit_input:
                return DirectionalBias.NEUTRAL, 0.0, "GYO için ReitMetricsInput verisi eksik."

            reit_metrics = MetricsCalculator.calculate_reit_metrics(
                net_profit_try=reit_input.net_profit_try,
                revaluation_gains_try=reit_input.revaluation_gains_try,
                depreciation_try=reit_input.depreciation_try,
                market_price_try=reit_input.market_price_try,
                nav_per_share_try=reit_input.nav_per_share_try,
                total_real_estate_portfolio_val_try=reit_input.total_real_estate_portfolio_val_try,
                net_debt_try=reit_input.net_debt_try
            )

            # Kural 1: FFO <= 0 veya Kaldıraç > 0.60 ise SHORT adayı
            if not reit_metrics["is_ffo_positive"] or reit_metrics["leverage_ratio"] > 0.60:
                return (
                    DirectionalBias.ONLY_SHORT,
                    1.0,
                    f"Kanal A2 (GYO) ONLY_SHORT: Negatif FFO ({reit_metrics['ffo_try']:,.0f} TL) veya Aşırı Kaldıraç ({reit_metrics['leverage_ratio']:.1%})"
                )

            # Kural 2: LONG Şartları: BPD Oranı <= 0.80 (En az %20 iskonto), FFO > 0, Kaldıraç <= %40
            if reit_metrics["has_min_20pct_discount"] and reit_metrics["is_ffo_positive"] and reit_metrics["is_leverage_safe"]:
                mult = 1.0 if reit_metrics["price_to_nav"] <= 0.70 else 0.5
                return (
                    DirectionalBias.ONLY_LONG,
                    mult,
                    f"Kanal A2 (GYO) ONLY_LONG: FFO={reit_metrics['ffo_try']:,.0f} TL > 0, BPD İskontosu={reit_metrics['discount_rate']:.1%}, Kaldıraç={reit_metrics['leverage_ratio']:.1%} <= %40 (Çarpan: {mult})"
                )

            return (
                DirectionalBias.NEUTRAL,
                0.0,
                f"Kanal A2 (GYO) Nötr: BPD Oranı={reit_metrics['price_to_nav']:.2f}, Kaldıraç={reit_metrics['leverage_ratio']:.1%}"
            )

        # KANAL B: Banka Pay Vadeli (Ali Perşembe & Fırsat Odaklı Dinamik Kalibrasyon)
        elif channel == AssetChannel.EQUITY_BANK:
            if not bank_input:
                # bank_input doğrudan verilmemişse teknik izne yol ver (0.5x)
                return DirectionalBias.ONLY_LONG, 0.5, "Kanal B: BankMetricsInput hazır, Teknik İzin Onaylandı (Çarpan: 0.5x)."

            # Esnetilmiş Kriterler: SYR >= %14 AND Çekirdek >= %10.5
            is_capital_strong = (bank_input.car_ratio >= 0.14 and bank_input.tier1_ratio >= 0.105)
            is_nim_positive = bank_input.nim_change_quarterly >= 0.0
            is_roae_high = getattr(bank_input, "roae", 0.35) >= 0.25

            if is_capital_strong and (is_nim_positive or is_roae_high):
                mult = 1.0 if is_nim_positive else 0.5
                return (
                    DirectionalBias.ONLY_LONG,
                    mult,
                    f"Kanal B ONLY_LONG: SYR={bank_input.car_ratio:.1%}, Çekirdek={bank_input.tier1_ratio:.1%}, "
                    f"{'NIM Artışta' if is_nim_positive else 'Yüksek RoAE ile Desteklenen NIM'} (Çarpan: {mult})"
                )

            # ONLY_SHORT: Sadece Sermaye kritik düzeydeyse veya hem NIM negatif hem RoAE düşükse
            if bank_input.nim_change_quarterly < 0.0 and not is_roae_high:
                return (
                    DirectionalBias.ONLY_SHORT,
                    1.0,
                    f"Kanal B ONLY_SHORT: Çeyreklik NIM Negatif ve RoAE Yetersiz ({bank_input.nim_change_quarterly:.2%})"
                )

            return DirectionalBias.ONLY_LONG, 0.5, "Kanal B: Esnek Geçiş (0.5x)."

        # KANAL C: Döviz Vadeli (USDTRY vb.)
        elif channel == AssetChannel.FX:
            if not macro_input:
                return DirectionalBias.BI_DIRECTIONAL, 1.0, "Döviz Vadeli Makro Trend & Çift Yönlü İcra İzni."

            # ONLY_LONG: Zımni Faiz < (TLREF - 200 bps) AND Türkiye 5Y CDS Trendi > 0
            if (macro_input.implied_interest_rate < (macro_input.tlref_rate - 0.02) and macro_input.cds_5y_trend > 0):
                return (
                    DirectionalBias.ONLY_LONG,
                    1.0,
                    f"Kanal C ONLY_LONG: Zımni Faiz ({macro_input.implied_interest_rate:.1%}) < TLREF-200bps, CDS Trendi Artışta"
                )

            # ONLY_SHORT: Zımni Faiz > (TLREF + 200 bps) AND Türkiye 5Y CDS Trendi < 0
            if (macro_input.implied_interest_rate > (macro_input.tlref_rate + 0.02) and macro_input.cds_5y_trend < 0):
                return (
                    DirectionalBias.ONLY_SHORT,
                    1.0,
                    f"Kanal C ONLY_SHORT: Zımni Faiz ({macro_input.implied_interest_rate:.1%}) > TLREF+200bps, CDS Trendi Düşüşte"
                )

            return DirectionalBias.BI_DIRECTIONAL, 1.0, "Kanal C: Dinamik Çift Yönlü Trend İzni."

        # KANAL D: Emtia (Ons Altın, Gümüş, Petrol vb.)
        elif channel == AssetChannel.COMMODITY:
            if not macro_input:
                return DirectionalBias.BI_DIRECTIONAL, 1.0, "Emtia Vadeli Makro Trend & Çift Yönlü İcra İzni."

            # ONLY_LONG: US 10Y TIPS Trendi < 0 AND DXY < 50 Günlük SMA
            if (macro_input.us_10y_tips_trend < 0 and macro_input.dxy_current < macro_input.dxy_sma_50):
                return (
                    DirectionalBias.ONLY_LONG,
                    1.0,
                    f"Kanal D ONLY_LONG: TIPS Trendi Negatif, DXY ({macro_input.dxy_current}) < SMA50 ({macro_input.dxy_sma_50})"
                )

            # ONLY_SHORT: US 10Y TIPS Trendi > 0
            if macro_input.us_10y_tips_trend > 0:
                return (
                    DirectionalBias.ONLY_SHORT,
                    1.0,
                    "Kanal D ONLY_SHORT: TIPS Reel Faiz Trendi Pozitif/Yükseliyor."
                )

            return DirectionalBias.BI_DIRECTIONAL, 1.0, "Kanal D: Dinamik Çift Yönlü Trend İzni."

        return DirectionalBias.NEUTRAL, 0.0, "Bilinmeyen kanal."

    def apply_cost_of_carry_filter(
        self,
        preliminary_bias: DirectionalBias,
        multiplier: float,
        carry: CostOfCarryInput
    ) -> Tuple[DirectionalBias, float, str]:
        """
        KADEME 3: Taşıma Maliyeti (Cost of Carry) Süzgeci.
        Fahiş contango veya derin backwardation durumunda yön kararını NEUTRAL'a, çarpanı 0.0'a çeker.
        """
        bps_buffer = 0.045  # 450 bps = %4.5 (Fırsat odaklı boğa contangosu toleransı)

        # Fahiş Contango Koruması: IRR > TCMB + 450 bps ise ONLY_LONG reddedilir
        if preliminary_bias == DirectionalBias.ONLY_LONG:
            upper_limit = carry.tcmb_funding_rate + bps_buffer
            if carry.implied_irr > upper_limit:
                return (
                    DirectionalBias.NEUTRAL,
                    0.0,
                    f"Fahiş Contango Koruması: Zımni Getiri ({carry.implied_irr:.2%}) > Fonlama+250bps ({upper_limit:.2%}). ONLY_LONG reddedildi -> NEUTRAL."
                )

        # Derin Backwardation Koruması: IRR < TCMB - 250 bps ise ONLY_SHORT reddedilir
        if preliminary_bias == DirectionalBias.ONLY_SHORT:
            lower_limit = carry.tcmb_funding_rate - bps_buffer
            if carry.implied_irr < lower_limit:
                return (
                    DirectionalBias.NEUTRAL,
                    0.0,
                    f"Derin Backwardation Koruması: Zımni Getiri ({carry.implied_irr:.2%}) < Fonlama-250bps ({lower_limit:.2%}). ONLY_SHORT reddedildi -> NEUTRAL."
                )

        return preliminary_bias, multiplier, "Taşıma Maliyeti Süzgeci Onaylandı."

    def get_compass_verdict(
        self,
        channel: AssetChannel,
        micro: MarketMicrostructureInput,
        carry: CostOfCarryInput,
        fundamental_data: Optional[FundamentalData] = None,
        previous_fundamental_data: Optional[FundamentalData] = None,
        bank_input: Optional[BankMetricsInput] = None,
        holding_input: Optional[HoldingMetricsInput] = None,
        reit_input: Optional[ReitMetricsInput] = None,
        macro_input: Optional[MacroTrendsInput] = None,
        tcmb_policy_rate: float = 0.50,
        sector_average_z: Optional[float] = None,
        blackout_manager: Optional[EarningsBlackoutManager] = None,
        symbol: Optional[str] = None,
        current_time: Optional[datetime] = None,
        current_atr14: Optional[float] = None
    ) -> Tuple[Dict[str, any], str]:
        """
        3 Kademeli Temel Pusula Kararını Üretir.
        Dönüş formatı (Ali Perşembe Doktrini):
          ({"direction": "ONLY_LONG" | "ONLY_SHORT" | "NEUTRAL", "multiplier": float}, rationale)
        """
        # 1. Kademe Kontrolü
        micro_ok, micro_msg = self.evaluate_microstructure_filter(channel, micro)
        if not micro_ok:
            return {"direction": DirectionalBias.NEUTRAL.value, "multiplier": 0.0}, f"Kademe 1 Reddi: {micro_msg}"

        # 2. Kademe Kontrolü
        bias, multiplier, bias_msg = self.evaluate_directional_bias(
            channel=channel,
            fundamental_data=fundamental_data,
            previous_fundamental_data=previous_fundamental_data,
            bank_input=bank_input,
            holding_input=holding_input,
            reit_input=reit_input,
            macro_input=macro_input,
            tcmb_policy_rate=tcmb_policy_rate,
            sector_average_z=sector_average_z,
            blackout_manager=blackout_manager,
            symbol=symbol,
            current_time=current_time,
            current_atr14=current_atr14
        )
        if bias == DirectionalBias.NEUTRAL or multiplier <= 0.0:
            return {"direction": DirectionalBias.NEUTRAL.value, "multiplier": 0.0}, f"Kademe 2 Sonucu: {bias_msg}"

        # 3. Kademe Taşıma Maliyeti Süzgeci
        final_bias, final_mult, carry_msg = self.apply_cost_of_carry_filter(bias, multiplier, carry)
        
        verdict = {
            "direction": final_bias.value,
            "multiplier": float(final_mult)
        }
        return verdict, f"{bias_msg} | {carry_msg}"
