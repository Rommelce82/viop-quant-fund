"""
Veri Şemaları Modülü (Data Schemas).

Lookahead Bias ve Data Leakage riskini engellemek için tüm veri modellerinde
'as_of_date' (verinin ait olduğu mali/takvim dönemi) ve 'announced_at' 
(verinin kamuya resmen açıklandığı kesin zaman damgası) alanları zorunludur.
"""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class BasePointInTimeSchema(BaseModel):
    """
    Tüm Point-in-Time veri modelleri için temel abstract model.
    Lookahead bias ve data leakage'a karşı zorunlu zaman damgası doğrulamalarını içerir.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(..., description="İlgili enstrüman veya hisse sembolü (Örn: THYAO, TCMB)")
    as_of_date: datetime = Field(
        ...,
        description="Verinin ait olduğu bilanço/istatistik referans tarihi (Dönem sonu)."
    )
    announced_at: datetime = Field(
        ...,
        description="Verinin piyasaya/KAP'a resmen açıklandığı kesin tescil zaman damgası."
    )
    source: str = Field(..., description="Veri kaynağı sağlayıcısı (Örn: FINTABLES_PRO, TCMB_EVDS)")


class FundamentalData(BasePointInTimeSchema):
    """
    Fintables PRO Çeyreklik Bilanço ve Temel Rasyo Veri Modeli.
    """
    period_year: int = Field(..., ge=2000, le=2100, description="Bilanço yılı (Örn: 2024)")
    period_quarter: int = Field(..., ge=1, le=4, description="Bilanço çeyreği (1, 2, 3 veya 4)")
    
    # Değerleme ve Finansal Rasyolar
    pe_ratio: Optional[float] = Field(None, description="Fiyat / Kazanç Oranı (F/K)")
    pb_ratio: Optional[float] = Field(None, description="Piyasa Değeri / Defter Değeri (PD/DD)")
    ev_ebitda: Optional[float] = Field(None, description="Firma Değeri / FAVÖK (FD/FAVÖK)")
    peg_ratio: Optional[float] = Field(None, description="F/K Büyüme Oranı (PEG)")
    
    # Karlılık ve Getiri Metrikleri
    roe: Optional[float] = Field(None, description="Özsermaye Karlılığı (ROE)")
    roa: Optional[float] = Field(None, description="Aktif Karlılığı (ROA)")
    net_profit_margin: Optional[float] = Field(None, description="Net Kar Marjı")
    gross_margin: Optional[float] = Field(None, description="Brüt Kar Marjı")
    ebitda_margin: Optional[float] = Field(None, description="FAVÖK Marjı")
    
    # Büyüme ve Borçluluk Metrikleri
    net_debt_ebitda: Optional[float] = Field(None, description="Net Borç / FAVÖK")
    current_ratio: Optional[float] = Field(None, description="Cari Oran (Likidite)")
    net_income_yoy_growth: Optional[float] = Field(None, description="Yıllık Net Kar Büyümesi")
    revenue_yoy_growth: Optional[float] = Field(None, description="Yıllık Satış Hasılatı Büyümesi")
    
    # Mutlak Finansal Büyüklükler (TRY)
    net_profit_try: float = Field(..., description="Net Dönem Karı (TL)")
    revenue_try: float = Field(..., description="Satış Hasılatı (TL)")
    ebitda_try: float = Field(..., description="FAVÖK (TL)")
    equity_try: float = Field(..., description="Toplam Özkaynaklar (TL)")


class SectoralData(BasePointInTimeSchema):
    """
    Sektörel Karşılaştırma ve Göreceli Değerleme Veri Modeli.
    """
    sector_name: str = Field(..., description="BIST Sektör Adı (Örn: ULASTIRMA, BANKA, METAL_ANA)")
    industry_avg_pe: float = Field(..., description="Sektör Ağırlıklı Ortalama F/K")
    industry_avg_pb: float = Field(..., description="Sektör Ağırlıklı Ortalama PD/DD")
    industry_avg_ev_ebitda: float = Field(..., description="Sektör Ağırlıklı Ortalama FD/FAVÖK")
    industry_avg_roe: float = Field(..., description="Sektör Ağırlıklı Ortalama ROE")
    relative_pe_to_sector: Optional[float] = Field(None, description="Şirket F/K / Sektör F/K Oranı")
    relative_pb_to_sector: Optional[float] = Field(None, description="Şirket PD/DD / Sektör PD/DD Oranı")


class KapNews(BasePointInTimeSchema):
    """
    KAP (Kamu Aydınlatma Platformu) Bildirim ve Duyuru Modeli.
    """
    news_id: str = Field(..., description="KAP Sistemindeki Benzersiz Bildirim ID")
    headline: str = Field(..., description="Bildirim Başlığı")
    disclosure_type: str = Field(
        ...,
        description="Bildirim Türü (Örn: ÖDA (Özel Durum Açıklaması), FR (Finansal Rapor), SPK)"
    )
    summary: str = Field(..., description="Bildirim Özeti veya Açıklama Gövdesi")
    raw_content: Optional[str] = Field(None, description="Bildirimin Tam Metni")
    is_price_sensitive: bool = Field(True, description="Fiyata Doğrudan Etki Edebilecek Nitelikte mi?")
    attachment_urls: List[str] = Field(default_factory=list, description="KAP Ek Dosya Bağlantıları")


class MacroData(BasePointInTimeSchema):
    """
    TCMB EVDS Makroekonomik Göstergeler Veri Modeli.
    """
    policy_rate: float = Field(..., description="TCMB 1 Hafta Vadeli Repo İhale Faiz Oranı (%)")
    overnight_lending_rate: Optional[float] = Field(None, description="TCMB Gecelik Borç Verme Faizi (%)")
    overnight_borrowing_rate: Optional[float] = Field(None, description="TCMB Gecelik Borçlanma Faizi (%)")
    
    # Enflasyon
    cpi_annual: float = Field(..., description="TÜFE Yıllık Yüzde Değişim")
    cpi_monthly: float = Field(..., description="TÜFE Aylık Yüzde Değişim")
    ppi_annual: Optional[float] = Field(None, description="ÜFE Yıllık Yüzde Değişim")
    
    # Döviz Kurları (TCMB Gösterge Alış/Satış)
    usd_try: float = Field(..., gt=0.0, description="TCMB Gösterge USD/TRY Kuru")
    eur_try: float = Field(..., gt=0.0, description="TCMB Gösterge EUR/TRY Kuru")
    
    # Rezervler ve Likidite (Milyar USD)
    gross_foreign_reserves_usd_bn: Optional[float] = Field(None, description="Brüt Döviz Rezervleri")
    net_international_reserves_usd_bn: Optional[float] = Field(None, description="Net Uluslararası Rezervler")
    swap_adjusted_net_reserves_usd_bn: Optional[float] = Field(None, description="Swap Hariç Net Rezervler")


class ViopContractInfo(BasePointInTimeSchema):
    """
    Fintables / BIST VİOP Sözleşmeler Listesi Modeli (08:30 Günlük).
    """
    symbol: str = Field("", description="Sözleşme veya dayanak sembolü")
    contract_code: str = Field(..., description="VİOP Sözleşme Kodu (Örn: F_THYAO1026, F_XU0301026)")
    underlying_symbol: str = Field(..., description="Dayanak Varlık Sembolü (Örn: THYAO, XU030, USDTRY)")
    asset_category: str = Field(..., description="Varlık Sınıfı (EQUITY, INDEX, COMMODITY, FX)")
    contract_size: float = Field(..., description="Sözleşme Büyüklüğü / Çarpanı (Örn: 100 pay, 10 endeks)")
    expiry_month: int = Field(..., ge=1, le=12, description="Vade Ayı")
    expiry_year: int = Field(..., ge=2020, le=2040, description="Vade Yılı")
    initial_margin_try: float = Field(..., gt=0.0, description="BIST Takasbank Başlangıç Teminatı (TL)")
    maintenance_margin_try: float = Field(..., gt=0.0, description="Sürdürme Teminatı (TL)")
    is_active: bool = Field(True, description="Sözleşme Aktif İşleme Açık mı?")


class ViopMarginInfo(BasePointInTimeSchema):
    """
    VİOP Başlangıç ve Sürdürme Teminatları Modeli (09:00 ve 14:00 Günlük 2 Kez).
    """
    symbol: str = Field("", description="Sözleşme Kodu")
    contract_code: str = Field(..., description="Sözleşme Kodu")
    initial_margin_try: float = Field(..., gt=0.0, description="Güncel Başlangıç Teminatı (TL)")
    maintenance_margin_try: float = Field(..., gt=0.0, description="Güncel Sürdürme Teminatı (TL)")
    session_window: str = Field(..., description="Güncelleme Penceresi ('09:00_OPEN' veya '14:00_MIDDAY')")
    margin_change_pct: float = Field(0.0, description="Önceki teminata göre değişim oranı (%)")


class MarginCallReport(BaseModel):
    """
    VİOP Teminat Tamamlama Çağrısı (Margin Call) Denetim Raporu (15 Dk Pasif + Bar Kapanışları).
    """
    model_config = ConfigDict(frozen=True)

    account_equity: float = Field(..., description="Hesap Toplam Özkaynağı (Nakit + Gerçekleşmemiş PnL)")
    total_initial_margin: float = Field(..., description="Açık Pozisyonlar İçin Gereken Toplam Başlangıç Teminatı")
    total_maintenance_margin: float = Field(..., description="Açık Pozisyonlar İçin Gereken Sürdürme Teminatı (%75-80)")
    free_margin: float = Field(..., description="Kullanılabilir Serbest Teminat (TL)")
    margin_ratio_pct: float = Field(..., description="Teminat Karşılama Oranı: (Özkaynak / Sürdürme Teminatı) * 100")
    margin_deficit_try: float = Field(0.0, description="Teminat Tamamlama Çağrısı Açığı (TL)")
    status: str = Field(..., description="'HEALTHY', 'WARNING_LEVEL', 'MARGIN_CALL_DEFICIT'")
    check_type: str = Field(..., description="'PASSIVE_15M', 'BAR_CLOSE_1415', 'BAR_CLOSE_1815'")
    timestamp: datetime = Field(..., description="Denetim Zaman Damgası")
    liquidation_required: bool = Field(False, description="Zorunlu Pozisyon Kapatma Gerekiyor mu?")
    target_liquidation_symbol: Optional[str] = Field(None, description="Kapatılması Önerilen En Riskli Sözleşme")


class AleFundEodReport(BaseModel):
    """
    Akbank ALE Fonu Seans Sonu (18:15) Net Nema Hesaplama Modeli.
    """
    model_config = ConfigDict(frozen=True)

    date_str: str = Field(..., description="İşlem Günü (YYYY-MM-DD)")
    idle_cash_try: float = Field(..., description="Saat 18:15 İtibarıyla Nemalandırılan Serbest Nakit")
    annual_gross_rate: float = Field(0.48, description="Yıllık Brüt Nema Oranı")
    daily_gross_yield_try: float = Field(..., description="Günlük Brüt Nema Tutarı (TL)")
    withholding_tax_pct: float = Field(0.175, description="Yasal Stopaj Kesintisi Oranı (%17.5)")
    withholding_tax_try: float = Field(..., description="Ödenen Stopaj Vergisi Tutarı (TL)")
    daily_net_yield_try: float = Field(..., description="Net Kasaya Eklenen ALE Neması (TL)")
    cumulative_ale_vault_try: float = Field(..., description="Kümülatif Birikmiş Güvenli ALE Kasası (TL)")
    calculated_at: datetime = Field(..., description="Hesaplama Zamanı (18:15)")

