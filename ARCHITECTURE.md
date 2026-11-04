# VİOP Kantitatif Serbest Fon (Hedge Fund) Algoritmik Ticaret Sistemi Mimarisi

Bu belge, Türkiye Vadeli İşlem ve Opsiyon Piyasası (VİOP) üzerinde çalışan, 3 senkronize karar motoruna (Temel, Haber/Duyarlılık, Teknik) ve sıfır toleranslı kantitatif risk yönetimi standartlarına sahip algoritmik ticaret sisteminin **Mimari Anayasası** ve yol haritasıdır.

---

## 1. Temel Prensipler ve Kırmızı Çizgiler

1. **Point-in-Time (Zaman Noktası) Veri Bütünlüğü & Data Leakage Önleme:**
   - Bilanço, KAP ve TCMB makro verilerinde açıklanma zaman damgası (`announced_at`) ve piyasaya erişim gecikmesi (`latency`) kesin olarak dikkate alınır.
   - Sonradan yapılan veri revizyonları geriye dönük testlerde (backtest) asla o tarihten önce kullanılamaz.
2. **Lookahead Bias Sıfır Toleransı:**
   - Karar motorları yalnızca bar kapanışında veya o mikro-saniyede kesinleşmiş verileri tüketir.
3. **Piyasa Rejimi Duyarlı Dinamik Parametreler (Overfitting Önleme):**
   - Sabit gösterge eşikleri yerine ATR, volatilite yüzdelikleri ve rejim tespiti (Trend, Yatay, Şok Volatilite) tabanlı dinamik eşikler kullanılır.
4. **VİOP Mikro-Yapı ve Takasbank Standartları:**
   - Sözleşme çarpanları (F_XU030 = 10, Pay VİOP = 100 vb.), Başlangıç Teminatı (Initial Margin), Sürdürme Teminatı (Maintenance Margin) ve Gün İçi/Gün Sonu Nemalandırma ve Margin Call risk hesaplamaları risk motoruna entegredir.

---

## 2. Dizin Yapısı (Modüler OOP)

```
src/
├── core/
│   ├── __init__.py
│   ├── config.py             # Sistem ayarları, sembol tanımları, VİOP çarpanları
│   └── models.py             # Event, Bar, Order, Position, Signal veri modelleri (Dataclasses/Pydantic)
├── data/
│   ├── __init__.py
│   ├── mcp_client.py         # MCP (Model Context Protocol) tabanlı veri istemcisi
│   ├── fintables_pipeline.py # Fintables PRO mali tablo ve temel rasyo veri hattı (Point-in-Time)
│   ├── tcmb_pipeline.py      # TCMB EVDS faiz, rezerv, enflasyon makro veri hattı
│   └── storage.py            # Zaman serisi önbellek ve veri saklama katmanı
├── engines/
│   ├── __init__.py
│   ├── base.py               # Soyut strateji ve karar motoru taban sınıfı
│   ├── fundamental.py        # Motor 1: Temel analiz & Evren seçimi (Universe Selection)
│   ├── sentiment.py          # Motor 2: KAP/Haber duyarlılık ve NLP skorlama motoru
│   ├── technical.py          # Motor 3: Rejim duyarlı teknik alfa üreteci
│   └── orchestrator.py       # 3 motorun ağırlıklı konsensüs sinyal orkestratörü
├── risk/
│   ├── __init__.py
│   ├── viop_margin.py        # Takasbank teminat ve Margin Call hesaplama motoru
│   ├── position_sizer.py     # Volatilite/Kelly/Risk tabanlı dinamik pozisyon boyutlandırma
│   └── stop_manager.py       # Dinamik ATR ve rejim tabanlı iz süren stop (Trailing Stop)
├── execution/
│   ├── __init__.py
│   ├── slippage_model.py     # Likidite ve spread duyarlı VİOP kayma modelleri
│   ├── event_bus.py          # Olay güdümlü (Event-Driven) dağıtım kuyruğu
│   └── simulator.py          # Gerçekçi VİOP backtest & canlı emir simülatörü
└── main.py                   # Sistem giriş noktası ve uçtan uca çalıştırma örneği
```

---

## 3. İnşa Aşamaları (Fazlar)
- **Faz 1:** Veri modelleri, yapılandırma ve Veri Hatları (MCP, Fintables PRO PIT, TCMB).
- **Faz 2:** 3 Karar Motoru (Temel Filtre, Duyarlılık, Rejim Duyarlı Alfa) ve Konsensüs Orkestratörü.
- **Faz 3:** VİOP Takasbank Teminat & Margin Call Motoru, Dinamik Pozisyon Boyutlandırma, İz Süren Stop.
- **Faz 4:** Olay Güdümlü Simülatör, Slippage & Komisyon Modeli, Uçtan Uca Entegrasyon.
