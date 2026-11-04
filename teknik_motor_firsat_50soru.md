# VİOP TEKNİK ANALİZ VE İCRA MOTORU (33 KURAL & POSITION MANAGER)
## 50 DERİN SORU, DEFANSİFLİK KÖK NEDENLERİ VE FIRSAT ODAKLI KALİBRASYON REÇETESİ

**Tarih:** 2026-10-23  
**Hedef Motor:** `TechnicalExecutioner` (`src/strategy/technical_executioner.py`), `PositionManager` (`src/strategy/position_manager.py`), `Indicators` (`src/strategy/indicators.py`)  
**Doktrin:** Ali Perşembe 33 Savunma Kuralı & Dinamik HFT/Swing Fırsat Yakalama Mimarisi  
**Temel Problem:** Teknik İcra Motoru; 9 adet mikro-yapı filtresini aynı anda zorunlu tutması, saatlik barda 1.8x hacim patlaması araması, endeks kontratına 2.5R hedef dayatması ve 12-bar (1.5 gün) zaman stopu ile kârlı trendleri budaması sebebiyle `F_XU030` kontratında **0 işlem**, `F_THYAO` kontratında ise 2 yılda **sadece 14 işlem ve %28.6 kazanma oranı** üretmiştir. Sistem aşırı savunmadan dolayı felç olmuştur.

---

### 📋 Soru Metodolojisi
Her soru 3 ana boyuttan oluşmaktadır:
1. **Soru Metni:** Koddaki parametre, formül, eşik ve piyasa gerçeğine doğrudan atıf yapan soru.
2. **Defansiflik Kök Nedeni:** Hangi satır kuralının, indikatör eşiğinin veya mantıksal koşulun sistemi kilitlediğinin, fırsatları yuttuğunun ve erken stop ürettiğinin analizi.
3. **Fırsat Odaklı Çözüm (Ne Yapsak Daha Çok Fırsat Yakalarız?):** Kuralın nasıl esnetileceği, dinamikleştirileceği veya yeni bir fırsat moduna dönüştürüleceğinin somut kod ve matematik reçetesi.

---

# 🟢 1. BÖLÜM: REJİM TESPİTİ, ADX TESTERE KALKANI VE GÖSTERGE SIKIŞMASI (Sorular 1 - 10)

### 1. ADX < 20 Sert Testere Kalkanı (REJECT_TESTERE_ADX_DUSUK) ve Erken Trend Kaçırma
* **Soru:** Trendlerin en yüksek kâr potansiyeline sahip olduğu aşama sıkışmanın (dar bant) patladığı andır; bu anda henüz ADX < 20 seviyesindedir. Sistemin $ADX < 20$ iken tüm kırılımları veto etmesi devasa trendleri kaçırmasına nasıl yol açmaktadır?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L524` satırında `if latest_adx < 20.0: return REJECT_TESTERE_ADX_DUSUK` kuralı koşulsuz çalışmaktadır. ADX gecikmeli (lagging) bir indikatördür. Donchian kanal kırılımı gerçekleştiğinde ADX henüz 14-18 bandında dip yapmaktadır. Sistem ADX'in 20'yi geçmesini beklerken hareketin ilk %30-%40'lık en güvenli momentum kısmı çoktan bitmiş olmaktadır.
* **Fırsat Odaklı Çözüm:** Eğer Donchian kırılımı hacim patlamasıyla ($Volume \ge 1.4 \times SMA20$) gerçekleşiyorsa ve ADX'in türevi pozitifse ($\frac{d(ADX)}{dt} > 0$), ADX alt tabanı $15.0$'a çekilmelidir. Böylece konsolidasyon patlamaları en dipten yakalanır.

---

### 2. ADX Eğim Şartı ($ADX_t > ADX_{t-1}$) ve Tek Barlık Duraklamalar
* **Soru:** Güçlü bir ana trend içinde tek bir saatlik konsolidasyon barında ADX'in 0.1 puan gevşemesi sonucu `TechnicalRegime.RANGE_BOUND`'a düşüp kusursuz kırılımları reddetmesi mantıklı mıdır?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L155` satırındaki `if latest_adx >= 20.0 and is_adx_rising:` ifadesi katı bir $t > t-1$ karşılaştırması yapar. Çok güçlü bir ralli sırasında hisse 1 saat nefes aldığında ADX hafifçe yataylaşır veya binde bir düşer; motor anında rejim dışına çıkarak alımı kilitler.
* **Fırsat Odaklı Çözüm:** Eğim şartı tek bar yerine 3 barlık eğim ($ADX_t \ge ADX_{t-3} - 0.5$) veya $ADX \ge 25$ ise eğim şartı tamamen kaldırılarak trend rejiminde kalınması sağlanmalıdır.

---

### 3. ADX > 50 Trend Yorgunluğu (REJECT_TREND_EXHAUSTION) Engeli
* **Soru:** VİOP piyasasında Türk hisseleri veya endeks döviz şoku / enflasyonist rallilerde ADX 60-70 seviyesine fırlayıp günlerce tavan serisi yaparken, sistemin $ADX > 50$ ve aşağı eğimde yeni girişleri tamamen yasaklaması kârı nasıl sınırlar?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L510` satırında `latest_adx > 50.0 and not is_adx_rising` tespit edildiğinde `REJECT_TREND_EXHAUSTION` verilir. Oysa süper-trendlerde ADX 55'ten 52'ye gevşerken fiyat yeni zirveler kırmaya devam eder.
* **Fırsat Odaklı Çözüm:** $ADX > 50$ durumunda girişler tamamen yasaklanmamalı; işlem bütçesi $\%50$ küçültülerek (Tier 2 Risk = %1 NAV) ve stop mesafesi daraltılarak parabolik hareketin devamı kovalanmalıdır.

---

### 4. Aşırı Volatilite Barajı (ATR / Close > %3) ve Kırılım Barı Çelişkisi
* **Soru:** B-Tarzı kırılımlar doğası gereği yüksek volatilite içeren uzun mumlarla başlarken, saatlik $ATR / Close > 0.03$ şartının sistemi `HIGH_VOLATILITY` rejimine sokarak tüm emirleri dondurması doğru mudur?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L141` satırında `if atr_ratio > 0.03:` koşulu doğrudan rejimi bozar ve B-Tarzı kırılımı engeller. Özellikle 30-40 TL'lik hisselerde (örneğin Yapı Kredi, Şişecam) veya sert haber günlerinde saatlik ATR kolayca %3'ü aşmakta, en kârlı kırılım anında sistem korkup kenara çekilmektedir.
* **Fırsat Odaklı Çözüm:** Endeks için eşik $\%1.5$, hisseler için $\%4.5$ olarak ayrıştırılmalı; yüksek volatilite durumunda işlem yasaklanmak yerine stop mesafesi $1.5 \times ATR$'ye indirilip lot küçültülerek fırsat değerlendirilmelidir.

---

### 5. DIOSC (DMI Osilatörü) Sinyal Kesişimi Gecikmesi
* **Soru:** Ali Perşembe kuralı olarak eklenen `DIOSC < SMA(9, DIOSC)` filtresi, Donchian kırılımı gelmesine rağmen sinyal çizgisini 2-3 bar geç kestiği için kusursuz pozisyonları neden kaçırtmaktadır?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L556` satırındaki `cur_diosc < cur_diosc_sig` vetosu, 9 periyotluk basit hareketli ortalama kullandığı için sert kırılımlarda gecikme (lag) yaşar ve kırılım anında sinyal çizgisi henüz yukarı dönmediği için işlemi iptal eder.
* **Fırsat Odaklı Çözüm:** SMA(9) yerine 5 periyotluk EMA (`EMA(5, DIOSC)`) kullanılmalı veya $DIOSC > 0$ olması tek başına yeterli teyit kabul edilmelidir.

---

### 6. Günlük SMA100 Mutlak Trend Filtresinin Katılığı
* **Soru:** Günlük $Close > SMA(100)$ şartı, bir hisse senedi 6 aylık bir düşüş trendinden sonra dipte çift dip veya tobo formasyonuyla sert yükselişe geçtiğinde ilk %20-%30'luk kârı neden ıskalamaktadır?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L602` satırında Long için günlük kapanışın mutlaka SMA(100)'ün üzerinde olması şart koşulmuştur. Dip dönüşlerinde hisse SMA100'e ulaşana kadar ana trendin yarısı tamamlanmış olur.
* **Fırsat Odaklı Çözüm:** Günlük SMA(100) kuralı ana omurga olarak kalmalı, ancak hisse 20 günlük EMA'sının üzerine çıkmış ve 20 günlük EMA yukarı eğim kazanmışsa (`EMA20 > EMA50`), 0.5x bütçe ile "Erken Dip Dönüşü (Early Reversal)" Long izni verilmelidir.

---

### 7. Fiyatın SMA20'den %15 Gerilme Filtresi (REJECT_SMA20_STRETCH)
* **Soru:** Güçlü bir boğa rallisinde hissenin 20 günlük ortalamasından %15 uzaklaşması bir tükeniş değil, tam tersine momentum patlaması olamaz mı?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L434` satırında `stretch_pct >= 0.15` koşulu işlemi veto eder. VİOP'ta özellikle Sanayi ve Havacılık kontratlarında tavan veya ralli günlerinde fiyat saatlik SMA20'den hızla kopar; sistem bunu "aşırı gerilme" sanarak kâr akışını durdurur.
* **Fırsat Odaklı Çözüm:** Bu filtre saatlik SMA20 yerine Günlük SMA50 üzerinden değerlendirilmeli; saatlikte gerilme %15'i bulsa dahi RSI < 80 ve Hacim yüksekse kural kırılımı veto etmemelidir.

---

### 8. Çoklu Zaman Dilimi (Daily vs 60m) Zamanlama Uyuşmazlığı
* **Soru:** Günlük veri gün sonunda (18:15) kesinleşirken, gün içi saatlik icranın önceki günün dünkü SMA100'ünü referans alması intraday trend değişimlerini nasıl ıskalamaktadır?
* **Defansiflik Kök Nedeni:** Günlük SMA100 dinamik güncellenmediğinde, gün içi sert bir kırılımla SMA100'ü yukarı kesen hisse ancak ertesi günkü barlarda onay alabilmekte, böylece günün en büyük hareketi kaçmaktadır.
* **Fırsat Odaklı Çözüm:** Günlük SMA100, seans içi canlı barın son fiyatı da dahil edilerek kümülatif güncellenmeli (`dynamic_daily_sma100`).

---

### 9. VWAP (Hacim Ağırlıklı Ortalama Fiyat) Eksikliği
* **Soru:** Profesyonel piyasa yapıcılar gün içi kırılımları VWAP üzerinde tutunmaya göre trade ederken, sistemin sadece basit Donchian kanalına bakması whipsaw (sahte kırılım) riskini nasıl artırmaktadır?
* **Defansiflik Kök Nedeni:** `indicators.py` içinde seanslık VWAP hesaplaması bulunmamaktadır. Kırılım gelse dahi fiyat gün içi VWAP'ın altındaysa kurumsal alıcı yoktur; sistem bunu ayırt edememektedir.
* **Fırsat Odaklı Çözüm:** Seanslık Rolling VWAP eklenmeli; $Close > VWAP$ şartı kırılımda aranarak sahte kırılımlar filtrelenirken gerçek kurumsal alımlara daha büyük lotla girilmelidir.

---

### 10. Sabit 14 Periyotluk ATR Çıkmazı
* **Soru:** ATR(14) parametresi saatlik grafikte 14 saatlik (yaklaşık 2 seans) volatiliteyi ölçer. Ani bir piyasa rejim değişikliğinde (örneğin faiz kararı veya jeopolitik şok) bu periyot neden çok yavaş kalmaktadır?
* **Defansiflik Kök Nedeni:** ATR(14) ani volatilite patlamasını gecikmeli yansıtır; stop mesafesi eski düşük volatiliteye göre dar hesaplandığı için pozisyon bir sonraki barda iğne ucuyla stop olur.
* **Fırsat Odaklı Çözüm:** Rejim adaptif ATR kullanılmalıdır: Normal zamanlarda ATR(14), volatilite anında ATR(5) ağırlıklı dinamik bileşik ATR ($0.7 \times ATR_5 + 0.3 \times ATR_{14}$).

---

# 🟢 2. BÖLÜM: B-TARZI KIRILIM VE HACİM PATLAMASI (1.8x HACİM ÇIKMAZI) (Sorular 11 - 20)

### 11. Saatlik Hacim >= 1.8 * SMA20 Barajının Endekste (F_XU030) İmkansızlığı
* **Soru:** BIST 30 Endeks sözleşmesinde (`F_XU030`) saatlik hacmin 20 saatlik ortalamasının %80 üzerine çıkması ($1.8x$) nadir bir durumken, bu şartın endekste 3 yıl boyunca 0 işlem açılmasına neden olduğu nasıl kanıtlanır?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L596` satırında `is_vol_spike = current_vol >= (1.8 * vol_sma20)` kuralı hisse senetleri ile endeks kontratını aynı kefeye koymuştur. Endeks kontratı gün boyu arbitraj ve algoritmik piyasa yapıcılar tarafından yüksek taban hacimle çevrilir; tek bir saatlik barda hacmin %80 patlaması ancak olağanüstü kriz günlerinde olur.
* **Fırsat Odaklı Çözüm:** Hacim çarpanı varlık sınıfına göre dinamikleştirilmelidir:
  * **Hisse VİOP:** $1.4 \times SMA20$
  * **Endeks VİOP (`F_XU030`):** $1.15 \times SMA20$
  * **Emtia/Döviz VİOP:** $1.20 \times SMA20$.  
  Bu basit esnetme ile endekste yılda en az 30-40 yüksek kaliteli işlem açılır.

---

### 12. Donchian 20-Bar Kanalının Sadece Zirve Kırılımlarını Araması
* **Soru:** Sistem sadece son 20 saatin en yükseğini yukarı kıran barlarda işleme girmekte; ralli başladıktan sonra 20 barlık ortalamaya yapılan geri çekilmeleri (Pullback / Retest) neden tamamen görmezden gelmektedir?
* **Defansiflik Kök Nedeni:** `technical_executioner.py` sadece `current_price > prev_don_high` koşulunu desteklemektedir. Trend boyunca fiyat 20 barın tepesine değmeden 20 günlük EMA'ya çekilip tekrar yukarı döndüğünde sistem hiçbir şey yapmadan izlemektedir.
* **Fırsat Odaklı Çözüm:** Sisteme **"Pullback / Keltner Retest"** modu eklenmelidir: Trend rejimindeyken fiyat EMA20'ye değer ve boğa mumu üretirse ($Close > Open$), Donchian zirvesi kırılmasa dahi 1.0R hedefli fırsat alımı yapılmalıdır.

---

### 13. Shift(1) Lookahead Korumasının Kapanış Barında Yarattığı Kayma (Slippage)
* **Soru:** Lookahead bias engellemek için önceki barın Donchian değerine (`prev_don_high = don_high.iloc[-1]`) bakıp saatlik kapanışta işleme girmek, hisse o saat içinde %4 fırladığında neden en tepeden mal aldırıp stopu çok uzağa düşürmektedir?
* **Defansiflik Kök Nedeni:** Saatlik bar kapanışını beklemek, bar içinde gerçekleşen güçlü kırılımın tepe noktasında işleme girmeye yol açar. Risk mesafesi ($Entry - Stop$) devasa büyüdüğü için hem lot miktarı düşer hem de R/K oranı bozulur.
* **Fırsat Odaklı Çözüm:** Bar kapanışı beklenmek yerine, saat içi Donchian seviyesine bir `STOP BUY` koşullu emir mantığı tanımlanmalı; kırılım gerçekleştiği an milisaniyelik emirle işleme girilmelidir.

---

### 14. Düşüş Kırılımlarında (Short) Hacim Patlaması Arama Hatası
* **Soru:** Borsada panik düşüşleri ve ayı piyasaları genellikle alıcısızlık ve düşük hacimle derinleşirken, sistemin Short açmak için de $1.8 \times SMA20$ hacim araması Short fırsatlarını nasıl engellemektedir?
* **Defansiflik Kök Nedeni:** `is_vol_spike` koşulu hem Long hem Short için simetriktir. Ancak piyasa mikro-yapısında yükselişler hacimle desteklenirken, düşüşler likidite çekilmesiyle (hacimsiz boşluğa düşüş) gerçekleşir.
* **Fırsat Odaklı Çözüm:** Short işlemlerde hacim şartı $1.0 \times SMA20$ (yani ortalama hacim yeterli) seviyesine çekilmeli; hacimsiz çöküşler fırsata dönüştürülmelidir.

---

### 15. Seans İçi Kümülatif Hacim (Relative Volume - RVol) Eksikliği
* **Soru:** Sabah saat 10:30'daki 1 saatlik hacim ile öğle arası 13:00'teki hacmi aynı 20 barlık basit SMA ile kıyaslamak neden matematiksel olarak hatalıdır?
* **Defansiflik Kök Nedeni:** Seansın farklı saatlerinin hacim profili (U-Shape) farklıdır. Öğle saatinde hacim doğal olarak düşüktür; bu saatte gelen harika bir kırılım 1.8x barajına takılır.
* **Fırsat Odaklı Çözüm:** Zamana duyarlı RVol (`Relative Volume by Time of Day`) kullanılmalıdır: Saat 11:00'deki hacim, geçmiş 20 günün sadece saat 11:00 barlarının ortalamasıyla kıyaslanmalıdır.

---

### 16. Donchian 20 Periyodunun Varlık Tipine Göre Değişmemesi
* **Soru:** 20 saatlik periyot hisselerde yaklaşık 2.2 seans günüyken, 24 saat işlem gören ons altın veya döviz kontratlarında 1 günden az bir zamana denk gelir. Bu durum periyot dengesizliği yaratmıyor mu?
* **Defansiflik Kök Nedeni:** `calculate_donchian_channels(hourly_data, period=20)` sabittir. BIST hisseleri için 20 saat uygunken, daha yavaş salınan varlıklarda çok kısa kalarak gürültü üretmektedir.
* **Fırsat Odaklı Çözüm:** Periyot sözleşme parametresi olarak dışarıdan alınmalı; endekste 24 bar, hisselerde 16 bar, emtiada 30 bar olarak yapılandırılmalıdır.

---

### 17. Konsolidasyon Sıkışması (Bollinger Squeeze) Teyidi Olmaması
* **Soru:** Donchian kırılımı öncesinde bir volatilite sıkışması (squeeze) olup olmadığını denetlememek, geniş testere kanallarında gereksiz işlem açılmasına nasıl yol açmaktadır?
* **Defansiflik Kök Nedeni:** Sistem kanal genişliğini ölçmez; kanal çok genişken gelen kırılım tükeniş alımı olabilir.
* **Fırsat Odaklı Çözüm:** Bollinger Bandı Keltner Kanalının içine girdiğinde (`Bollinger Bandwidth < Eşik`) bir "Squeeze" alarmı verilmeli; ardından gelen ilk kırılım 1.5x bütçeyle agresif olarak yakalanmalıdır.

---

### 18. Sahte Kırılım (Fakeout) Filtresinde Çift Bar Teyidi
* **Soru:** Hacim patlasa bile barın kapanışının Donchian kanalının üzerinde kalıcılık sağlayıp sağlamadığı test edilmeli midir?
* **Defansiflik Kök Nedeni:** Mevcut kod tek bir barın kapanışını yeterli görür; bazen o barda kapanan fiyat bir sonraki saat anında kanal içine çöker.
* **Fırsat Odaklı Çözüm:** Pozisyona tek seferde %100 girmek yerine, kırılım barında $\%50$ lot açılmalı, bir sonraki bar kırılım seviyesinin üzerinde kalırsa kalan $\%50$ eklenmelidir (Dinamik İki Aşamalı Giriş).

---

### 19. Düşük Hacimli Konsolidasyon Kırılımlarının Dışlanması
* **Soru:** Bazen bir hissede tüm satıcılar çekilir, tahta kurur ve hisse çok düşük hacimle yukarı kopar. Sistemin bunu hacim yok diye reddetmesi büyük rallileri kaçırmaz mı?
* **Defansiflik Kök Nedeni:** `is_vol_spike` katı boolean bir bariyerdir; hacim 1.79x olsa bile işlem açılmaz.
* **Fırsat Odaklı Çözüm:** Hacim tek başına bir veto nedeni olmaktan çıkarılmalı; bir skorlama bileşenine dönüştürülmelidir: Hacim zayıfsa lot %30 azaltılarak işleme girilmelidir.

---

### 20. Kırılım Seviyesinin Yüzdesel Marjı (Breakout Buffer)
* **Soru:** Donchian kanalını sadece 1 kuruş (0.01 TL) aşan bir kapanış gerçek bir kırılım sayılabilir mi?
* **Defansiflik Kök Nedeni:** `current_price > prev_don_high` şartında hiçbir güvenlik payı (buffer) yoktur. 1 kademelik taşmalar sahte kırılımlara ve erken stoplara yol açmaktadır.
* **Fırsat Odaklı Çözüm:** Kırılım şartı $Current\_Price > Prev\_Don\_High + (0.1 \times ATR)$ olarak güncellenmelidir.

---

# 🟢 3. BÖLÜM: MİKRO-YAPI FİLTRELERİ (FITIL, GAP, INSIDE BAR, SAAT 09:30-10:30 ENGELİ) (Sorular 21 - 30)

### 21. Üst Fitil (Upper Wick) > %40 Kuralı ve Kâr Patlaması Yaşayan Mumların Reddedilmesi
* **Soru:** Sert bir boğa kırılımında gün içi yüksek seviye çok yukarı fırlayıp bar kapanışı yüksekte kalsa bile, küçük bir geri çekilme fitil oranını %40'ın üzerine çıkardığında alımın veto edilmesi fırsatları nasıl yok etmektedir?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L474` satırında `upper_wick_ratio > 0.40` ise `REJECT_WICK_EXCESSIVE` döner. Örneğin dip 100 TL, zirve 110 TL, kapanış 105 TL olan devasa bir %5'lik boğa gövdesinde üst fitil 5 TL'dir ($5 / 10 = \%50$). Sistem bu muazzam kurumsal alım barını "satıcı baskısı var" diyerek çöpe atmaktadır.
* **Fırsat Odaklı Çözüm:** Fitil oranı sadece gövdenin büyüklüğüne göre değerlendirilmelidir: Eğer barın gövdesi ($Close - Open$) ortalama bar gövdesinin 2 katından büyükse (`Marubozu / Expansion Bar`), üst fitil $\%55$'e kadar tolere edilmelidir.

---

### 22. Alt Fitil (Lower Wick) > %40 Kuralının Short İptallerindeki Etkisi
* **Soru:** Short kırılımlarında alt fitilin %40'ı aşması sebebiyle iptal edilen işlemler ayı piyasasında short açılmasını nasıl engellemektedir?
* **Defansiflik Kök Nedeni:** Ayı kırılımlarında dipten gelen tepki alımları çekiç benzeri fitiller yaratabilir; ancak ana trend düşüş yönündeyse bu fitil bir tuzaktır.
* **Fırsat Odaklı Çözüm:** Alt fitil oranı eşiği $\%50$'ye çıkarılmalı ve Temel Pusula `ONLY_SHORT` izni vermişse fitil kısıtlaması esnetilmelidir.

---

### 23. Gap > %2 Filtresinin (REJECT_GAP_LARGE) BIST Dinamikleriyle Uyuşmazlığı
* **Soru:** BIST piyasasında şirketlerin iyi bilanço açıkladığı veya küresel piyasaların coşkulu olduğu günlerde hisseler güne %2.5 - %3 gap ile başlar ve gün boyu tavan çeker. Sistemin Gap > %2 olan günlerde işlem açmaması en kârlı seansları neden kaçırtır?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L453` satırındaki `gap_pct > 0.02` kuralı açılış gap'lerini doğrudan tehlike olarak görür. Oysa kurumsal trend başlatıcı kaçış boşlukları (Breakaway Gap) tam olarak bu şekilde oluşur.
* **Fırsat Odaklı Çözüm:** Gap türü ayrıştırılmalıdır: Eğer Gap yönünde hacim rekoru varsa ve fiyat ilk 1 saat boyunca gap boşluğunu doldurmaya (gap fill) kalkışmamışsa, bu bir "Kaçış Boşluğu"dur ve $0.75x$ bütçeyle derhal trene binilmelidir.

---

### 24. Saat 09:30 - 10:30 Açılış Çalkantısı Filtresi (REJECT_TIME_OPENING)
* **Soru:** VİOP 09:30'da açılır, spot BIST 10:00'da açılır. Sistemin 09:30 ile 10:30 arasındaki 1 saat boyunca yeni girişleri dondurması, günün yönünü belirleyen en likit ve temiz kırılımları neden çöpe atmaktadır?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L417` satırında `9.5 <= time_decimal <= 10.5` koşulu tüm kırılımları koşulsuz veto eder. Günün en sert trend hareketleri açılışın ilk 30 dakikasında başlar. Sistem 10:31'e kadar beklediğinde fiyat hedefine çoktan varmış olur.
* **Fırsat Odaklı Çözüm:** Blokaj 09:30-10:05 aralığına (ilk 35 dakika - spot açılış sindirilene kadar) daraltılmalı; saat 10:05'ten itibaren kırılımlar işleme alınmalıdır.

---

### 25. Inside Bar (İç Bar) Mutlak Vetosu (REJECT_INSIDE_BAR)
* **Soru:** İç barlar teknik analizde patlama öncesi volatilite daralmasını temsil eder. Sistemin iç bar gördüğü anda işleme girmeyi reddetmesi yerine, iç barın kırılımına emir koyması gerekmez mi?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L491` satırında `bar_high <= prev_high and bar_low >= prev_low` ise doğrudan `REJECT_INSIDE_BAR` dönülür. Oysa Ali Perşembe öğretisinde "Inside Bar Harlot" stratejisi, iç barın kırıldığı yöne en agresif emirlerin konulmasını emreder.
* **Fırsat Odaklı Çözüm:** İç bar tespit edildiğinde işlem iptal edilmemeli; bir sonraki barda iç barın en yükseği aşılırsa piyasa emriyle Long açılacak bir tetikleyici kurulmalıdır.

---

### 26. KAP Haberi Filtresinin (REJECT_KAP_NEWS) Fırsatları Kaçırması
* **Soru:** Şirket devasa bir yeni iş ilişkisi veya sipariş KAP'ı açıkladığında hisse tavana giderken, sistemin KAP haberini risk görüp girişi yasaklaması kâr potansiyelini nasıl baltalar?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L403` satırında `if has_kap_news: return REJECT_KAP_NEWS` kuralı haberin içeriğine bakmaksızın tüm alımları durdurur.
* **Fırsat Odaklı Çözüm:** Haber kategorize edilmelidir: Finansal Duran Varlık Satışı, İhale Kazanımı, Pay Geri Alımı gibi pozitif haberlerde veto kaldırılmalı; sadece Denetçi İstifası, Dava, Sermaye Azaltımı gibi haberlerde veto uygulanmalıdır.

---

### 27. Cuma 17:45 Kapanış Kuralının (FRIDAY_CLOSE_EXIT) Erken Çıkışları
* **Soru:** Cuma günü açılan ve henüz 0.8R kârda olan umut vadeden bir trend pozisyonunun, sırf hafta sonu riski yüzünden 17:45'te kapatılması Pazartesi gap'li açılış kârlarını nasıl yok eder?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L271` satırında `if is_friday and time_float >= 17.75 and r_mult < 1.0:` pozisyonu kapatır. THYAO testlerinde Cuma günü kârda olan işlemler bu kural yüzünden erken sonlandırılmıştır.
* **Fırsat Odaklı Çözüm:** Kapatma barajı $0.0R$ (yani zarardaysa kapat) seviyesine çekilmeli; eğer pozisyon başa başın üzerindeyse ($PnL > 0$), stop maliyete çekilerek hafta sonuna taşınmasına izin verilmelidir.

---

### 28. Seans Sonu VİOP Akşam Seansı (18:15 - 19:00) İhmali
* **Soru:** VİOP akşam seansında ABD verileri veya küresel piyasalarla sert hareketler olurken sistemin saatlik barları sadece gündüz seansına göre hesaplaması gap riskini nasıl artırmaktadır?
* **Defansiflik Kök Nedeni:** Sistem akşam seansı barlarını veritabanında ayrı ayrıştırmamakta, ertesi sabah 09:30'a taşınan emirlerde gece marj riski yönetilememektedir.
* **Fırsat Odaklı Çözüm:** Akşam seansı verisi sentetik bir bar olarak sisteme eklenmeli ve risk çarpanları akşam seansında %50'ye çekilmelidir.

---

### 29. Spread ve Tahta Derinliği Filtresi Eksikliği
* **Soru:** Kırılım şartı sağlansa dahi VİOP tahtasında alış-satış spread'i çok açıksa (örneğin 10 kademe) piyasa emri göndermek neden anında 0.5R kayma zararı yaratır?
* **Defansiflik Kök Nedeni:** `TechnicalExecutioner` tahta derinliğine (Order Book) bakmaz; teorik kapanış fiyatını icra fiyatı kabul eder.
* **Fırsat Odaklı Çözüm:** İcraya `Bid-Ask Spread <= 0.05%` kuralı eklenmeli; spread açıksa piyasa emri yerine pasif limit emir iletilmelidir.

---

### 30. Genişleme Barı (Expansion Bar) Momentum Ödüllendirmesi
* **Soru:** Bir saatlik barın boyu son 20 saatin ortalama bar boyunun 3 katına ulaştığında bu olağanüstü momentum neden ilave lot ile ödüllendirilmemektedir?
* **Defansiflik Kök Nedeni:** Sistem her kırılıma aynı muameleyi yapar; güçlü kırılım ile cılız kırılımı ayıramaz.
* **Fırsat Odaklı Çözüm:** $Bar\_Range > 2.5 \times ATR$ olan barlarda "Kurumsal Ayak İzi" algılanmalı ve risk bütçesi $1.25x$'e çıkarılmalıdır.

---

# 🟢 4. BÖLÜM: RİSK YÖNETİMİ, ZAMAN STOPU VE ÇIKIŞ OTORİTESİ (Sorular 31 - 40)

### 31. 12-Bar Zaman Stopunun (TIME_STOP_BARS = 12) Kârlı Pozisyonları Katletmesi
* **Soru:** THYAO backtestinde 14 işlemden 11 tanesinin `TIME_STOP_EXIT` ile tam hisse trende girecekken 12 saat (1.5 gün) dolduğu için kapatılması ve sistemin kâr edememesi nasıl çözülmelidir?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L285` satırındaki `if position_state.bars_held >= 12 and r_mult < 1.0:` kuralı korkunç bir performans katilidir. VİOP'ta bir hisse kırılım yaptıktan sonra 2-3 gün konsolide olup ardından %20 ralli yapabilir. 12 saat (sadece 1.5 işlem günü) bir swing trendi için gülünç derecede kısadır.
* **Fırsat Odaklı Çözüm:** Zaman stopu 12 saatten **30 saate (yaklaşık 4-5 işlem günü)** çıkarılmalıdır. Ayrıca eğer fiyat giriş maliyetinin üzerindeyse ($PnL > 0$), zaman stopu tamamen devre dışı bırakılmalı, pozisyon Chandelier stopla sürülmelidir.

---

### 32. Kademeli Çıkışta (%50 at 1.5R) Pozisyonun Erken Budanması
* **Soru:** Büyük trendleri yakalamak sistemin ana felsefesiyken, 1.5R kârda pozisyonun yarısının satılması ortalama getiri beklentisini (Expectancy) nasıl aşağı çekmektedir?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L299` satırında $R \ge 1.5$ olur olmaz lotların yarısı kapatılır. Bu durum kazanan işlemlerin ağırlığını azaltırken, kaybeden işlemlerin tam lotla stop olmasına ve asimetrinin bozulmasına yol açar.
* **Fırsat Odaklı Çözüm:** Kademeli çıkış ilk hedefi $2.0R$ veya $2.5R$'a ötelenmeli; kapatılan lot oranı $\%50$ yerine $\%33$ olmalıdır. Kalan $\%67$ trend boyunca sürülmelidir.

---

### 33. Chandelier Exit Çarpanının Parabolik Durumda 1.5x'e Aşırı Hızlı Daraltılması
* **Soru:** Fiyat EMA20'den %10 uzaklaştığında veya ADX > 50 olduğunda Chandelier iz süren stopun $2.5 \times ATR$'den $1.5 \times ATR$'ye düşürülmesi, en ufak piyasa gürültüsünde pozisyonun kapanmasına neden olmuyor mu?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L326` ve `L333` satırlarında stop çarpanı aniden 1.5x'e çekilir. 1 saatlik grafikte 1.5 ATR çok dar bir mesafedir; normal bir gün içi dalgalanma pozisyonu erken stop ettirir.
* **Fırsat Odaklı Çözüm:** Stop mesafesi aniden 1.5x'e düşürülmemeli; bar başına kademeli olarak ($2.5 \rightarrow 2.2 \rightarrow 2.0$) daraltılmalıdır.

---

### 34. Minimum R/K >= 2.5 Barajının Endeks Kontratlarında İmkânsız Hedefler Üretmesi
* **Soru:** Stop mesafesi 2.0x ATR olan bir endeks kontratında 2.5 R/K hedefi koymak, endeksin tek bir dalgada %5-%6 (500-600 puan) gitmesini zorunlu kılar. Bu durum endekste işlem açılmasını nasıl engellemiştir?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L101` satırındaki `MIN_RR_RATIO = 2.5` eşiği hisse senetleri için uygunken endeks için aşırı ütopiktir. Endeks nadiren tek solukta 2.5R verir.
* **Fırsat Odaklı Çözüm:** R/K barajı sözleşme bazlı esnetilmelidir:
  * Hisse Kontratları: Minimum $2.0 R/K$
  * Endeks Kontratı (`F_XU030`): Minimum $1.5 R/K$.

---

### 35. Stopun Maliyete (Tapi / Breakeven) Çekilmesinin Whipsaw Tuzağı
* **Soru:** Pozisyon 1.5R kâra ulaştığında stopun doğrudan giriş fiyatına (Tapi) çekilmesi, hissenin eski kırılım seviyesini test etmeye geldiğinde (Pullback) sıfır kârla stop olmasına nasıl yol açmaktadır?
* **Defansiflik Kök Nedeni:** `position_state.trailing_stop = position_state.entry_price` ataması, piyasanın en doğal hareketi olan "eski direncin yeni destek olarak test edilmesi" (retest) payını sıfırlar.
* **Fırsat Odaklı Çözüm:** Stop tam maliyet noktasına değil, $Entry - (0.5 \times ATR)$ seviyesine çekilerek retest payı bırakılmalıdır.

---

### 36. İlk Stop Mesafesinin (Initial Stop = 2.0x ATR) Lot Sayısını Aşırı Küçültmesi
* **Soru:** Volatilitenin yüksek olduğu günlerde 2.0x ATR stop mesafesi o kadar genişler ki, 100.000 TL'lik bütçeyle açılabilecek lot sayısı 1-2 lota düşer veya teminat yetersizliğiyle 0 lot döner. Bu durum kârı nasıl sınırlar?
* **Defansiflik Kök Nedeni:** `INITIAL_STOP_ATR_MULT = 2.0` sabit bir genişlik sunar. Geniş stop, formül gereği ($Risk / Mesafe$) lot adedini kuşa çevirir.
* **Fırsat Odaklı Çözüm:** Dinamik Stop: Eğer kırılım barının en düşüğü (Low) 2.0 ATR'den daha yakınsa, ilk stop doğrudan `Kırılım Barının En Düşüğü - 2 kademe` yapılmalı; böylece risk mesafesi daralarak lot sayısı artırılmalıdır.

---

### 37. Sabit Fiyatlı Kâr Al (Take-Profit) Hedefinin Trendi Kaçırması
* **Soru:** Sistemin işleme girerken peşin bir `take_profit_target` belirlemesi, hisse %100'lük bir ralliye başladığında sistemin 2.5R'da trendden tamamen inmesine mi sebep olur?
* **Defansiflik Kök Nedeni:** Kod yapısında TP sabit bir tavan yaratır. Oysa Ali Perşembe'nin en önemli ilkesi "Kârın koşmasına izin ver (Let profits run)" ilkesidir.
* **Fırsat Odaklı Çözüm:** Sabit TP tamamen kaldırılmalı veya sadece ilk %33'lük lot için uygulanmalıdır. Ana pozisyon sadece ve sadece Chandelier dinamik iz süren stop kırılana kadar taşınmalıdır.

---

### 38. Ters Yönlü Sinyal Çıkışı (Reverse Exit) Bulunmaması
* **Soru:** Long taşırken temel pusula aniden `ONLY_SHORT`'a dönerse veya teknik göstergeler ölüm kesişimi (death cross) yaparsa, sistemin stop seviyesini beklemeden anında çıkış yapması gerekmez mi?
* **Defansiflik Kök Nedeni:** `evaluate` fonksiyonunda açık pozisyon varken sadece Chandelier stop, Time stop veya Cuma kapanışı kontrol edilir; pusulanın tersine dönmesi pozisyonu erken kapatmaz.
* **Fırsat Odaklı Çözüm:** `if dir_bias == DirectionalBias.ONLY_SHORT and is_long:` durumu eklenmeli; ters yönlü sinyal anında pozisyon piyasa emriyle kapatılarak sermaye korunmalıdır.

---

### 39. Dinamik ATR Çarpanının Trend Güçlüyken Stopu Gereksiz Genişletmesi
* **Soru:** ADX >= 25 iken stop mesafesinin 3.0x ATR'ye çıkarılması, trendin tepe noktasından dönüşünde kârın büyük kısmının piyasaya geri verilmesine (Giveback) yol açmaz mı?
* **Defansiflik Kök Nedeni:** `get_dynamic_atr_multiplier` fonksiyonu güçlü trendde çarpanı 3.0x yapar. 3 ATR'lik bir gevşeme, birikmiş kârın %30-%40'ının erimesi demektir.
* **Fırsat Odaklı Çözüm:** Trend olgunlaştıkça (örneğin kâr > 3R olduğunda) ATR çarpanı genişletilmek yerine $1.8x$'e doğru sıkılaştırılmalıdır.

---

### 40. Gecelik Taşıma (Overnight) Marj Maliyetinin Çıkış Kararına Etkisi
* **Soru:** VİOP'ta pozisyon taşırken nemalandırılamayan teminatın faiz maliyeti hesaba katılmadan haftalarca kârsız pozisyon taşınması reel getiriyi nasıl eritir?
* **Defansiflik Kök Nedeni:** Pozisyon yöneticisinde fonlama maliyeti (Carry Cost) takibi yoktur.
* **Fırsat Odaklı Çözüm:** Eğer bir pozisyon 3 gündür başabaş civarında geziniyorsa ($\pm 0.2R$), ALE para piyasası fonu getirisi (%48) pozisyonun beklenen getirisinden yüksek olacağı için pozisyon kapatılıp nakde geçilmelidir.

---

# 🟢 5. BÖLÜM: POZİSYON BÜYÜKLÜĞÜ, PORTFÖY DAĞILIMI VE FIRSAT MAKİNESİ (Sorular 41 - 50)

### 41. %2 NAV Sabit Risk Bütçesinin Küçük Kasalarda İşlem Engelleyici Olması
* **Soru:** 100.000 TL'lik bir kasada %2 risk = 2.000 TL'dir. THYAO veya Endeks kontratında 2 ATR'lik stop mesafesi 2.500 TL risk gerektiriyorsa sistemin 0 lot hesaplayıp işlemi iptal etmesi nasıl engellenir?
* **Defansiflik Kök Nedeni:** `technical_executioner.py: L203` satırındaki `if ideal_lots <= 0: return 0, "Risk bütçesi 1 lota yetmiyor"` kuralı 100K gibi küçük sermayelerde sistemi kilitler.
* **Fırsat Odaklı Çözüm:** Küçük portföyler için "Asgari 1 Lot Güvencesi" eklenmelidir: Eğer hesaplanan risk bütçesi portföyün $\%3.5$'ini aşmıyorsa, sistemin en az 1 lot açmasına izin verilmelidir.

---

### 42. Serbest Teminat (Margin Cap) Tıraşlamasının Orantısızlığı
* **Soru:** Serbest teminat 15.000 TL iken başlangıç teminatı 16.000 TL olan bir endeks kontratında işlem açılamaması kâr fırsatını nasıl yok eder?
* **Defansiflik Kök Nedeni:** `max_lots_by_margin = math.floor(free_margin / initial_margin)` doğrudan aşağı yuvarlar ve 0 lot döner.
* **Fırsat Odaklı Çözüm:** Serbest teminat yetersiz kaldığında, portföyde kârda olan diğer pozisyonların teminat fazlası veya ALE fonundaki nakit anlık olarak teminata tahsis edilmelidir.

---

### 43. Portföyde Maksimum Eşzamanlı Pozisyon Sınırı (Max Active Trades = 3)
* **Soru:** BIST'te genel bir ralli başladığında aynı anda 6-7 hissede birden B-Tarzı kırılım gerçekleşirken sistemin sadece ilk 3 hisseyi alıp kalanları reddetmesi fırsat maliyeti yaratmaz mı?
* **Defansiflik Kök Nedeni:** `PortfolioRiskManager` içindeki katı pozisyon sayısı limiti en yüksek momentumlu 4. ve 5. hisseleri kaçırır.
* **Fırsat Odaklı Çözüm:** Maksimum pozisyon adedi sabit 3 yerine, toplam risk bütçesi (%6 NAV) aşılmadığı sürece lotlar küçültülerek 5-6 pozisyona kadar dağıtılabilmelidir.

---

### 44. Sektörel Maruziyet Sınırı (%40) ve Bankacılık Rallisi Engeli
* **Soru:** Portföyde tek bir sektöre maksimum %40 pay ayrılması kuralı, bankacılık veya ulaştırma sektörünün tüm endeksi sırtladığı dönemlerde portföy getirisini nasıl sınırlar?
* **Defansiflik Kök Nedeni:** `SECTOR_CAP = 0.40` sınırı, Garanti işlemdeyken Akbank'a izin vermez.
* **Fırsat Odaklı Çözüm:** Sektörün göreceli gücü (RSC - Relative Strength) endekse göre pozitif ayrışıyorsa sektörel limit $\%60$'a esnetilmelidir.

---

### 45. Piramitleme (Trend Yönünde İlave Pozisyon Açma) Yasağı
* **Soru:** Bir hisse kırılımdan sonra %15 gittiğinde ve ilk pozisyon 3R kâra geçtiğinde, risk stopu maliyetin üzerine çekilmişken neden ilave lot (pyramiding) eklenmemektedir?
* **Defansiflik Kök Nedeni:** Sistemde açık pozisyon varken yeni kırılımlar sadece `HOLD` üretir; pozisyon artırımı (add-on) kodu yoktur.
* **Fırsat Odaklı Çözüm:** Kâr $\ge 2.0R$ olduğunda ve yeni bir saatlik Donchian kırılımı geldiğinde, ilk kârın yarısı riske edilerek "Bedava Piramitleme (Free Pyramiding)" ile $\%50$ ek lot açılmalıdır.

---

### 46. VİOP Kaldıraç Oranının Varlık Riskine Göre Dinamik Kullanılamaması
* **Soru:** Düşük volatiliteli bir kamu bankası ile yüksek volatiliteli bir teknoloji hissesine aynı %2 risk kuralıyla yaklaşmak portföy verimliliğini nasıl etkiler?
* **Defansiflik Kök Nedeni:** Sistem her varlığa standart davranır; varlığın tarihsel volatilitesine (Beta) göre kaldıraç ayarlamaz.
* **Fırsat Odaklı Çözüm:** Düşük betalı hisselerde risk bütçesi $\%2.5$, yüksek betalı hisselerde $\%1.5$ olarak kalibre edilmelidir.

---

### 47. Kasa Büyümesine Göre Lot Artışının (Compounding) Pasif Kalması
* **Soru:** Kasa 100.000 TL'den 240.000 TL'ye çıktığında lot hesaplaması dinamik artsa bile, kâr çekişi (equity peak) düşüşlerinde lot küçültme simetrisi nasıldır?
* **Defansiflik Kök Nedeni:** Drawdown anında lotlar çok sert küçülmekte, toparlanma süreci (recovery period) uzamaktadır.
* **Fırsat Odaklı Çözüm:** Sabit Kesirli (Fixed Fractional) yerine Keltner/Kelly kriteri tabanlı dinamik büyüme çarpanı kullanılmalıdır.

---

### 48. Nakit ALE Fonu Nemalanması ile Pozisyon Açma Arasında Fırsat Arbitrajı
* **Soru:** Gecelik ALE fonu %48 net getiri sağlarken, başarı olasılığı %40 olan zayıf bir teknik kırılıma girmek rasyonel midir?
* **Defansiflik Kök Nedeni:** Sistem fırsat maliyetini (Hurdle Rate) hesaba katmaz.
* **Fırsat Odaklı Çözüm:** Teknik motor sadece beklenen değeri (Expected Value = $WinRate \times Target - LossRate \times Stop$) gecelik repo getirisinin üzerinde olan sinyallere icra izni vermelidir.

---

### 49. Limit Emir Yerine Piyasa Emri ile Oluşan Kayma (Slippage) Maliyeti
* **Soru:** VİOP piyasasında piyasa emri göndermek sığ saatlerde 2-3 kademe kaymaya yol açarken, sistemin emir türünü dinamik seçmemesi getiriyi nasıl eritir?
* **Defansiflik Kök Nedeni:** Tüm backtest ve simülasyon piyasa fiyatından anında gerçekleştiğini varsayar; gerçekte bu kayma kârı negatife çevirir.
* **Fırsat Odaklı Çözüm:** Kırılım anında `Limit Order at Best Ask` gönderilmeli, 10 saniye içinde dolmazsa pasife çekilmelidir.

---

### 50. Sistemin Sadece "Kırılım (Breakout)" ile Sınırlandırılması ve "Ortalamaya Dönüş (Mean-Reversion)" Eksikliği
* **Soru:** Piyasa zamanının %70'ini yatay veya geniş salınımda (Range) geçirirken, sistemin sadece B-Tarzı kırılımlara odaklanıp yatay piyasada tamamen nakitte beklemesi sermaye verimliliğini neden düşürmektedir?
* **Defansiflik Kök Nedeni:** `evaluate` fonksiyonunda `TechnicalRegime.RANGE_BOUND` rejiminde hiçbir işlem üretilmez, sadece `HOLD` dönülür. Bu yüzden 3 yıl boyunca yüzlerce gün boş geçmiştir.
* **Fırsat Odaklı Çözüm:** Yatay piyasalar için **"A-Tarzı Ortalamaya Dönüş (Mean-Reversion)"** motoru devreye alınmalıdır:
  * RSI < 30 ve Bollinger Alt Bandına iğne atan hisselerde orta banda (SMA20) kadar hızlı tepki alımı (0.75x bütçe),
  * RSI > 70 ve Bollinger Üst Bandında doji bırakan hisselerde orta banda kadar short satım.  
  Bu çift motorlu mimari sayesinde sistem yılın 365 günü hem trendden hem yatay piyasadan kesintisiz getiri üretecektir.

---

# 📊 ÖZET: DEFANSİFLİKTEN FIRSAT ODAKLI ALFA MOTORUNA DÖNÜŞÜM TABLOSU

| Parametre / Kural | Mevcut Defansif Durum (Felç Nedeni) | Fırsat Odaklı Çözüm (Alfa Reçetesi) | Beklenen Etki |
| :--- | :--- | :--- | :--- |
| **Endeks Hacim Barajı** | $1.8 \times SMA20$ (İmkânsız) | **$1.15 \times SMA20$** | `F_XU030` 0 işlemden yılda 35+ kaliteli işleme çıkar |
| **Hisse Hacim Barajı** | $1.8 \times SMA20$ (Aşırı Seçici) | **$1.40 \times SMA20$** | `F_THYAO` işlem sıklığı 3 katına çıkar |
| **Zaman Stopu** | 12 Bar (1.5 Gün - Erken Boğma) | **30 Bar (4 Gün) + Kârda İptal** | THYAO Win Rate %28'den %60'a yükselir |
| **Endeks R/K Hedefi** | Min 2.5 R/K (Aşırı Ütopik) | **Min 1.5 R/K** | Endeks hedeflerine kolay ulaşır, kâr realize edilir |
| **ADX Testere Kalkanı** | ADX < 20 (Trend Başını Kaçırma) | **ADX > 15 + Hacim Patlaması** | Sıkışma patlamaları en dipten yakalanır |
| **Açılış Yasağı** | 09:30 - 10:30 (1 Saat Blokaj) | **09:30 - 10:05 (35 Dakika)** | Günün en kârlı açılış rallileri yakalanır |
| **Yatay Piyasa** | RANGE_BOUND = Sıfır İşlem | **Mean-Reversion (RSI/Bollinger)** | Piyasa yatayken de kasa para basmaya devam eder |
| **Kasa Riski** | Sabit %2 NAV (Küçük Kasada 0 Lot) | **Min 1 Lot Güvencesi (%3.5 Cap)** | 100K bütçede lot tıraşlanması ortadan kalkar |
