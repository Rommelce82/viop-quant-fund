# VİOP TEMEL ANALİZ VE YÖN PUSULASI MOTORU
## 50 DERİN SORU, DEFANSİFLİK KÖK NEDENLERİ VE FIRSAT ODAKLI KALİBRASYON REÇETESİ

**Tarih:** 2026-10-23  
**Hedef Motor:** `FundamentalCompass` (`src/strategy/fundamental_compass.py`), `MetricsCalculator` (`src/strategy/metrics_calculator.py`)  
**Doktrin:** Kurumsal Kantitatif Alfa Üretimi & Ali Perşembe Dinamik Adaptasyon Mimarisi  
**Temel Problem:** Temel Analiz Karar Motoru, aşırı katı kurallar ve faiz artış döngüsünü dikkate almayan sabit eşikler sebebiyle `F_AKBNK` ve `F_XU030` kontratlarında **3 yıl boyunca 0 işlem** açılmasına yol açmış; sistemi tamamen felç ederek fırsatları kaçırmıştır.

---

### 📋 Soru Yapısı
Her soru 3 ana boyuttan oluşmaktadır:
1. **Soru Metni:** Koddaki parametre ve anayasal formüle doğrudan atıf yapan soru.
2. **Mevcut Defansifliğin Kök Nedeni:** Hangi satır kuralının sistemi korkaklığa ve sıfır işleme sürüklediğinin analizi.
3. **Fırsat Odaklı Çözüm (Ne Yapsak Daha Çok Fırsat Yakalarız?):** Formülün ve motorun nasıl esnetilmesi ve alfa üreten fırsat odaklı bir yapıya dönüştürülmesi gerektiğinin reçetesi.

---

# 🟢 1. BÖLÜM: BANKACILIK KANALI (KANAL B) VE NET FAİZ MARJI (NIM) ÇIKMAZI (Sorular 1 - 10)

### 1. Faiz Artış Döngüsünde Daralan NIM Kuralı ve Borsa Rallisi Çatışması
* **Soru:** TCMB politika faizini hızla artırırken Net Faiz Marjı ($\Delta NIM < 0$) daralan banka hisseleri nominal bir enflasyon rallisi yaşarken, sistemin AKBNK'ta kesintisiz `ONLY_SHORT` izni vermesi ve teknik motorun `Günlük Fiyat > SMA100` şartıyla çatışarak 3 yıl boyunca 0 işlem açması nasıl çözülmelidir?
* **Defansiflik Kök Nedeni:** `fundamental_compass.py: L217` satırında yer alan `if bank_input.nim_change_quarterly < 0.0: return DirectionalBias.ONLY_SHORT` kuralı mutlak bir prangadır. Faiz artışında mevduat faizi hemen fırlayıp kredi getirisi gecikmeli arttığı için tüm Türk bankalarında NIM negatifleşmiş ve sistem bankacılık rallisini tamamen kaçırmıştır.
* **Fırsat Odaklı Çözüm:** $\Delta NIM < 0$ olsa dahi, eğer bankanın Özkaynak Kârlılığı ($RoAE$) beklenen enflasyonun üzerindeyse veya Komisyon Gelirleri Büyümesi $> \%50$ ise `ONLY_SHORT` yerine bütçe çarpanı $0.5x$ olan **`ONLY_LONG (Tier 2)`** iznine geçişe imkan tanınmalıdır.

---

### 2. Sermaye Yeterlilik Rasyosu (SYR) %16 Barajının Aşırı Seçiciliği
* **Soru:** Bankalarda Long pozisyon izni almak için aranan $SYR \ge \%16$ barajı, BDDK'nın yasal asgari sınırı olan $\%12$'ye ve kurumsal hedef olan $\%14$'e kıyasla kârlı bankaları gereksiz yere eliyor mu?
* **Defansiflik Kök Nedeni:** `fundamental_compass.py: L208` kodundaki `bank_input.car_ratio >= 0.16` şartı, sermayesini aktif olarak krediye dönüştürüp devasa kâr yazan özel bankaları (Garanti, Akbank, İş Bankası) sınırda bırakmakta veya elemektedir.
* **Fırsat Odaklı Çözüm:** Eşik değeri $SYR \ge \%14.0$ seviyesine esnetilmeli; bankanın son 1 yıllık temettü ödeme gücü ve kâr büyümesi yüksekse çarpan $1.0x$ seviyesinde korunmalıdır.

---

### 3. Çekirdek Sermaye Oranı (Tier 1) %12 Kısıtı
* **Soru:** Çekirdek Sermaye Oranının $\%12$ üzerinde olmasını zorunlu tutan kural, kredi genişlemesi dönemlerinde kârlılık rekoru kıran bankalarda işlem açılmasını nasıl engellemektedir?
* **Defansiflik Kök Nedeni:** `bank_input.tier1_ratio >= 0.12` filtresi, sermaye benzeri kredi kullanan ancak operasyonel gücü çok yüksek bankaların yön iznini sıfırlamaktadır.
* **Fırsat Odaklı Çözüm:** Tier 1 eşiği $\%10.5$'e çekilmeli; eğer Takipteki Krediler Oranı ($NPL$) $\%2$'nin altındaysa bu esneklik otomatik devreye girmelidir.

---

### 4. Ücret ve Komisyon Gelirlerinin Dikkate Alınmaması
* **Soru:** Faiz dışı gelirlerin (kredi kartı, sigorta, varlık yönetimi, transfer ücretleri) bankacılık net kârının $\%40$'ına ulaştığı dönemlerde, sadece geleneksel faiz marjına ($\Delta NIM$) bakmak sistemi neden kör bırakmaktadır?
* **Defansiflik Kök Nedeni:** Bilanço motorunda ücret ve komisyon büyümesini denetleyen hiçbir kod satırı bulunmamaktadır. NIM daralırken komisyon patlaması yaşayan bankalar haksız yere Short'a itilmektedir.
* **Fırsat Odaklı Çözüm:** `BankMetricsInput` sınıfına `fee_commission_yoy_growth: float` alanı eklenmeli; faiz dışı gelir büyümesi enflasyonu aşıyorsa NIM daralması veto edilerek Long kanalı açılmalıdır.

---

### 5. Fiyat / Defter Değeri (PD/DD) İskontosunun Yön Pusulasına Bağlanması
* **Soru:** Türk bankalarının küresel benzerlerine göre $\%50 - \%60$ iskontolu ($PD/DD < 0.70$) işlem gördüğü dönemlerde, makro rasyolar hafif bozuk olsa dahi bu devasa değerleme fırsatı sisteme nasıl Long izni olarak yansıtılmalıdır?
* **Defansiflik Kök Nedeni:** Mevcut bankacılık motoru sadece rasyoların trendine bakmakta, hissenin piyasa değerlemesini ($PD/DD$, $F/K$) tamamen göz ardı etmektedir.
* **Fırsat Odaklı Çözüm:** Eğer Banka $PD/DD \le 0.75$ ve Tarihsel Medyan iskontosuna göre ucuz ise, $\Delta NIM < 0$ olsa dahi sistem `NEUTRAL` veya `ONLY_LONG (0.5x)` izni vermelidir.

---

### 6. Aktif Kalitesi (NPL ve Stage 3 Karşılık) Kalkanı
* **Soru:** Takipteki Krediler Oranı ($NPL$) düşen ve Stage 3 karşılık oranı $\%80$'in üzerinde olan bir banka defansif olarak kusursuzken, sadece faiz döngüsü yüzünden dışlanması doğru mudur?
* **Defansiflik Kök Nedeni:** Banka motorunda aktif kalitesini ödüllendiren pozitif bir çarpan katmanı eksiktir.
* **Fırsat Odaklı Çözüm:** $NPL < \%2.0$ ve Karşılık Oranı $\ge \%75$ olan bankalara "Aktif Kalite Bonusu" verilerek bütçe çarpanı $1.0x$'a yükseltilmelidir.

---

### 7. Faiz İndirim Döngüsünün Öncü Fiyatlanması (Forward-Looking NIM)
* **Soru:** Piyasa faiz indirimlerini 3-6 ay önceden satın alırken, motorun sadece geçmiş çeyreğin açıklanmış (lagging) bilançosundaki negatif NIM'e bakması banka hissesi dipten dönerken Short pozisyon açtırmaz mı?
* **Defansiflik Kök Nedeni:** Kod tamamen geçmişe dönük (historical backward-looking) bilanço verisiyle beslenmekte; tahvil faizlerinin gerilediği ve bankaların marj açacağı beklentisini yakalayamamaktadır.
* **Fırsat Odaklı Çözüm:** 2 Yıllık Gösterge Tahvil faizinin 50 günlük ortalamasının altına inmesi durumunda bankalarda "NIM Genişleme Beklentisi" tetiklenmeli ve geçmiş çeyrek marjı ne olursa olsun Short izni yasaklanıp Long izni açılmalıdır.

---

### 8. Enflasyon Karşısında Reel Özkaynak Kârlılığı ($RoAE - Enflasyon$)
* **Soru:** Bankanın nominal özkaynak kârlılığı $\%35$ iken enflasyon $\%50$ ise reel sermaye erir; ancak nominal kârlılık $\%60$ iken enflasyon $\%40$ ise banka reel sermaye büyütür. Bu ayrım koda nasıl işlenmelidir?
* **Defansiflik Kök Nedeni:** Banka kârlılığı risksiz getiri veya enflasyon ile kıyaslanmamakta, sadece nominal NIM eğimine bakılmaktadır.
* **Fırsat Odaklı Çözüm:** $RoAE > TCMB\_Enflasyon\_TÜFE$ olduğu çeyreklerde banka hissesi doğrudan `ONLY_LONG` aday listesine alınmalıdır.

---

### 9. Çeyreklik Bilanço Bekleme Gecikmesi (Stale Data Lag)
* **Soru:** Bir çeyreklik bilanço açıklandıktan sonraki 3 ay boyunca aynı rasyonun kullanılması, çeyreğin ortasında bankanın fonlama maliyetleri çöktüğünde neden yeni fırsatları kaçırır?
* **Defansiflik Kök Nedeni:** `bank_input` verisi yalnızca çeyrek sonlarında güncellenmekte, ara dönemdeki BDDK haftalık bülten verileri motor tarafından tüketilmemektedir.
* **Fırsat Odaklı Çözüm:** BDDK'nın haftalık yayınladığı sektör net kâr ve kredi/mevduat makas verileri öncü sinyal olarak `bank_input` içine enjekte edilmelidir.

---

### 10. Kamu Bankası - Özel Banka Ayrımı
* **Soru:** Kamu bankaları düşük kâr marjıyla görev zararı/sübvansiyonlu kredi yazabilirken, özel bankaların kârlılık odaklı çalışması aynı Kanal B motorunda nasıl modellenmelidir?
* **Defansiflik Kök Nedeni:** Tüm banka vadelileri (AKBNK, GARAN, HALKB, VAKBN) aynı eşiklerle değerlendirilmektedir.
* **Fırsat Odaklı Çözüm:** Özel bankalar için kârlılık ($NIM$, $RoAE$), kamu bankaları için ise sermaye enjeksiyonu ve aktif büyüklüğü bazlı dinamik iki ayrı eşik matrisi tanımlanmalıdır.

---

# 🟢 2. BÖLÜM: REEL SEKTÖR (KANAL A) BİLANÇO RASYOLARI VE PRANGALAR (Sorular 11 - 20)

### 11. Piotroski F-Skorunda $F \ge 7$ Şartının Aşırı Elitistliği
* **Soru:** Borsa İstanbul gibi gelişmekte olan piyasalarda 9 üzerinden 7 puan alabilen şirket sayısı bir elin parmaklarını geçmezken, $F \ge 7$ şartı fırsat evrenini $\%90$ oranında daraltmıyor mu?
* **Defansiflik Kök Nedeni:** `fundamental_compass.py: L175` satırındaki katı filtreler sadece mükemmel şirketlere izin vermekte, "kötüden iyiye dönen" büyüme hisselerini kaçırmaktadır.
* **Fırsat Odaklı Çözüm:** $F \ge 5$ alan şirketlere bütçe çarpanı $0.5x$ olarak giriş izni verilmeli; F-Skoru bir önceki çeyreğe göre 2 puan artmışsa ($\Delta F \ge +2$) momentum primiyle $1.0x$ yapılmalıdır.

---

### 12. Enflasyon Ortamında Cari Oran ve Varlık Devir Hızı Bozulması
* **Soru:** F-Skorunun 6. kriteri (Cari Oran artışı) ve 9. kriteri (Varlık Devir Hızı artışı), enflasyon ortamında işletme sermayesi ihtiyacı ve yeniden değerleme yüzünden kaç hissede hatalı sıfır puan üretmektedir?
* **Defansiflik Kök Nedeni:** Enflasyonist büyümede şirketlerin stok maliyeti katlandığı için cari oran düşebilir; bu operasyonel bir başarısızlık değil, enflasyonist stok biriktirmedir.
* **Fırsat Odaklı Çözüm:** Stok devir hızı artıyorsa cari oran düşüşü F-Skorunda cezalandırılmamalı, tam puan verilmelidir.

---

### 13. Altman Z-Skorunda $Z \ge 2.60$ Güvenli Bölge Barajı
* **Soru:** Yüksek borçla devasa yatırım yapan ulaştırma (THY), telekom ve perakende şirketlerinin Z-Skoru geleneksel imalat formülünde 2.10 - 2.40 (gri bölge) çıkarken, $2.60$ eşiği bu devleri Long'dan eliyor mu?
* **Defansiflik Kök Nedeni:** `fundamental_compass.py: L160` satırında $Z < 2.60$ olan hisseler Tier 1 olamamakta, momentum yoksa doğrudan elenmektedir.
* **Fırsat Odaklı Çözüm:** Sektörel medyan Z-Skor referansı getirilmelidir. Havacılıkta medyan $Z = 2.00$ ise, $Z=2.30$ alan hisse sektörüne göre güçlü sayılarak tam bütçe Long izni almalıdır.

---

### 14. Net Borç / FAVÖK > 3.5 Olduğunda Otomatik Short Zorlaması
* **Soru:** Yeni fabrika veya filo yatırımı yapan ve döviz geliri olan bir ihracatçı şirkette Net Borç / FAVÖK $3.8$ çıktığında sistemin hisseye zorla `ONLY_SHORT` vermesi ne gibi tehlikeler yaratır?
* **Defansiflik Kök Nedeni:** `fundamental_compass.py: L167` satırında `net_debt_ebitda > 3.5` ifadesi doğrudan Short üretmektedir. Ralli yapan güçlü bir şirket sadece borçlu olduğu için açığa satılmakta ve zarar yazmaktadır.
* **Fırsat Odaklı Çözüm:** Şirketin İhracat Oranı $> \%40$ veya Özkaynakları artış eğilimindeyse, borçluluk tek başına Short sebebi olmamalı, `NEUTRAL` statüsüne çekilmelidir.

---

### 15. FAVÖK Vekil Nakit Akışının (CFO Proxy) Eksikliği
* **Soru:** Nakit Akış Tablosundaki gerçek İşletme Faaliyetlerinden Nakit Akışı ($CFO$) yerine sadece $FAVÖK$ vekilinin kullanılması, net kârı yüksek ama kasasına 1 kuruş nakit girmeyen şirketleri nasıl Long yapar?
* **Defansiflik Kök Nedeni:** Gerçek nakit dönüşüm süresi ve serbest nakit akışı ihmal edilmekte, tahakkuk anomalileri tam tespit edilememektedir.
* **Fırsat Odaklı Çözüm:** Fintables MCP'den gelen nakit akım tablosundaki gerçek `operating_cash_flow_try` doğrudan kullanılmalı; $\frac{\text{Gerçek CFO}}{\text{Net Kâr}} \ge 0.70$ şartı aranmalıdır.

---

### 16. %50 Faiz Ortamında $ROIC > WACC$ Şartının Felç Yaratması
* **Soru:** TCMB politika faizinin $\%50$ olduğu bir ekonomide, risksiz getiriye risk primi eklendiğinde $WACC = \%58$ çıkmaktadır. Türkiye'de $\%58$ üzerinde ROIC üretebilen neredeyse hiçbir şirket yokken bu kural sistemi neden kurutmuştur?
* **Defansiflik Kök Nedeni:** `MetricsCalculator.calculate_wacc()` risksiz faiz olarak $\%50$'yi aldığında sermaye maliyeti uçmakta, şirketler ekonomik katma değer (EVA) üretemiyor görünmektedir.
* **Fırsat Odaklı Çözüm:** $WACC$ hesabında kullanılan risksiz faiz, 10 yıllık reel tahvil getirisi üzerinden enflasyondan arındırılmış reel faizle (örn. $\%15-\%20$) revize edilmelidir.

---

### 17. Ekonomik Katma Değer (EVA) Spread Esnekliği
* **Soru:** $ROIC - WACC$ farkı negatif olsa bile, şirketin çeyreklik satış hasılatı büyümesi enflasyonun 2 katı ise bu şirket dışlanmalı mıdır?
* **Defansiflik Kök Nedeni:** Yüksek büyüme evresindeki teknoloji ve perakende hisseleri kâr marjı düşük olduğu için $ROIC < WACC$ tuzağına düşer.
* **Fırsat Odaklı Çözüm:** Satış Hasılatı Büyümesi $> \%60$ olan büyüme hisselerinde EVA kriteri aranmamalıdır.

---

### 18. F-Skor 5 Olan Şirketlerde Değerleme İskontosu Desteği
* **Soru:** Bilanço skoru 5/9 olan ancak $F/K = 3.5$ ve $FD/FAVÖK = 4.0$ olan kelepir bir sanayi hissesine Long izni verilmemesi kurumsal fon felsefesine aykırı değil midir?
* **Defansiflik Kök Nedeni:** F-Skoru düşük olan hisse ne kadar ucuz olursa olsun motor tarafından doğrudan elenmektedir.
* **Fırsat Odaklı Çözüm:** Sektör çarpanlarına göre en ucuz $\%20$'lik dilimde olan hisselerde F-Skor eşiği 5'e indirilmeli ve $0.5x$ çarpanla işlem açılabilmelidir.

---

### 19. Net İşletme Sermayesi (NWC) Dönüşüm Hızı
* **Soru:** Şirketin alacak tahsil süresi kısalırken borç ödeme süresi uzuyorsa (negatif işletme sermayesiyle fonlanma), bilanço puanı düşük olsa bile bu şirket nakit makinesi değil midir?
* **Defansiflik Kök Nedeni:** İşletme sermayesi döngüsü mevcut rasyolarda ölçülmemektedir.
* **Fırsat Odaklı Çözüm:** Nakit Dönüş Süresi ($CCC \le 0$) olan perakende şirketlerine (BIMAS, MGROS) rasyo puanına bakılmaksızın Long izin bonusu verilmelidir.

---

### 20. Bilanço Döneminde Ciro Artışı / Enflasyon Filtresi
* **Soru:** Şirket net kârını artırmış görünse de cirosu enflasyonun altında büyümüşse bu bir kârlılık illüzyonu mudur?
* **Defansiflik Kök Nedeni:** Enflasyonist ciro erimesi filtrelenmediği için sahte kârlı hisselere Long verilmektedir.
* **Fırsat Odaklı Çözüm:** $Reel\ Ciro\ Büyümesi = Ciro\ Artışı - TÜFE > 0$ şartı Long iznine ön koşul yapılmalıdır.

---

# 🟢 3. BÖLÜM: TAŞIMA MALİYETİ (CARRY / IRR) VE ARBİTRAJ ENGELLERİ (Sorular 21 - 30)

### 21. Fahiş Contango Filtresinin (%2.5 / 250 bps) Long'u Felç Etmesi
* **Soru:** $IRR > Fonlama + 250$ bps olduğunda Long pozisyonun toptan yasaklanması, temettü beklentisinin ve yüksek faiz beklentisinin vadeliye yansıdığı güçlü boğa trendlerinde sistemi neden tamamen nakde çekmektedir?
* **Defansiflik Kök Nedeni:** `fundamental_compass.py: L289` satırında Zımni Repo oranı fonlamayı 250 bps aştığında Long yönü doğrudan `NEUTRAL` yapılmaktadır. Boğa piyasalarında vadeli kontratlar doğal olarak primli işlem görür!
* **Fırsat Odaklı Çözüm:** Fahiş Contango sınırı sabit 250 bps yerine, hissenin tarihsel basis volatilitesinin 2 standart sapması ($+2\sigma$) olarak dinamikleştirilmelidir.

---

### 22. Temettü Verimi Düşülmemiş Zımni Faiz Hesabı
* **Soru:** Mart-Mayıs temettü sezonunda hissenin ödeyeceği temettü spot fiyattan düşülmeden zımni faiz hesaplandığında, kontrat hatalı bir şekilde "fahiş contango" bölgesinde mi görünmektedir?
* **Defansiflik Kök Nedeni:** $IRR$ formülünde beklenen temettülerin indirgenmiş nakit değeri çıkarılmamakta, bu da yapay bir yüksek faiz algısı yaratarak Long iznini kilitletmektedir.
* **Fırsat Odaklı Çözüm:** $F_{teorik} = (S_0 - PV(Temettü)) \times e^{r \times t}$ formülü işletilmeli; temettüden arındırılmış net IRR hesaplanmalıdır.

---

### 23. Derin Backwardation Krizinde Short Yasağının Yarattığı Korunmasızlık
* **Soru:** Piyasa çökerken vadeli fiyat aşırı iskontolu işlem gördüğünde ($IRR < Fonlama - 250$ bps), sistemin Short yönü yasaklaması portföyün açığa satışla korunmasını (hedge) nasıl engellemektedir?
* **Defansiflik Kök Nedeni:** `apply_cost_of_carry_filter` fonksiyonu aşırı iskontoda Short'u keserek kriz düşüşlerinden kâr edilmesini veya portföyün korunmasını imkansız kılmaktadır.
* **Fırsat Odaklı Çözüm:** Portföy betası $> +0.50$ iken derin backwardation olsa dahi hedge amaçlı Endeks vadelisinde Short açılmasına izin verilmelidir.

---

### 24. Vadeye 5 Gün Kala Yıllıklandırma Çarpanının Patlaması
* **Soru:** Vade sonu yaklaşırken formüldeki $365 / t$ çarpanı sebebiyle birkaç kademelik fiyat oynamasının zımni faizi $\%200$ veya $\% -100$ yapması filtreyi nasıl sakatlar?
* **Defansiflik Kök Nedeni:** Gün sayısı $t < 5$ iken formül aşırı duyarlı hale gelmekte ve hatalı contango/backwardation kararları üretmektedir.
* **Fırsat Odaklı Çözüm:** Vadeye 7 iş günü kala Cost of Carry filtresi cari vade yerine bir sonraki aktif vadeli kontrata (Next Month Contract) devredilmelidir.

---

### 25. Cash-and-Carry Arbitraj Bacağının Otonom Tetiklenmesi
* **Soru:** Fahiş contango tespit edildiğinde yön kararını `NEUTRAL` yapmak yerine, spot hisse alıp vadeli sözleşme satan risksiz Cash-and-Carry arbitrajı koda neden eklenmemiştir?
* **Defansiflik Kök Nedeni:** Karar motoru sadece spekülatif tek bacaklı yön izinleri üretmekte; borsa içi risksiz taşıma arbitrajı yetkisine sahip değildir.
* **Fırsat Odaklı Çözüm:** Fahiş contangoda spekülatif Long yasaklanırken, portföydeki nakit tamponu ile anında sentetik risksiz repo getirisi sağlayan arbitraj emri tetiklenmelidir.

---

### 26. Reverse Cash-and-Carry İmkansızlığı
* **Soru:** Derin backwardation olduğunda spot hisse satıp vadeli kontrat alma arbitrajı Borsa İstanbul'da açığa satış kısıtlamaları varken uygulanabilir mi?
* **Defansiflik Kök Nedeni:** Pratikte ödünç hisse piyasası likiditesi olmadığı için bu bacak teoride kalmaktadır.
* **Fırsat Odaklı Çözüm:** Portföyde fiziki olarak taşınan hisseler varsa bu arbitraja izin verilmeli, çıplak açığa satış arbitrajı kısıtlanmalıdır.

---

### 27. Basis Volatilite Bantları (Bollinger Basis)
* **Soru:** Sabit 250 bps yerine hissenin son 20 günlük vadeli-spot basis farkının 2 standart sapmalık Bollinger bandı kullanılsaydı kaç hatalı blokaj engellenirdi?
* **Defansiflik Kök Nedeni:** Sabit bps parametresi volatil hisselerle sığ hisseleri aynı kefeye koymaktadır.
* **Fırsat Odaklı Çözüm:** Dinamik $Basis\ Z-Score$ modeli kurularak $Z_{basis} > 2.0$ olduğunda contango uyarısı verilmelidir.

---

### 28. Döviz Vadelisinde (USDTRY) Zımni Faiz Sapması
* **Soru:** Döviz vadelisinde zımni faiz TLREF'in 200 bps altına indiğinde Long açılması kuralı, TCMB'nin kur korumalı mevduat ve döviz müdahaleleri yaptığı dönemlerde sistemi neden ters köşeye yatırır?
* **Defansiflik Kök Nedeni:** Döviz vadeli fiyatı piyasa faiz paritesinden ziyade merkez bankası rezerv politikasıyla belirlenmektedir.
* **Fırsat Odaklı Çözüm:** Zımni faize ek olarak Forward Implied Yield Curve ve Swap limitleri girdi olarak kullanılmalıdır.

---

### 29. Gecelik TCMB Depo Alım İhalesi Sapması
* **Soru:** TCMB piyasada likidite fazlası olduğunda gecelik faizi politika faizinin altına (%47) düşürdüğünde, koddaki sabit %50 politika faizi referansı taşıma maliyeti hesabını bozar mı?
* **Defansiflik Kök Nedeni:** Sabit politika faizi kullanılmakta, Takasbank BPP gecelik ağırlıklı ortalama fonlama faizi çekilmemektedir.
* **Fırsat Odaklı Çözüm:** TCMB MCP istemcisi üzerinden canlı TCMB AOFM (Ağırlıklı Ortalama Fonlama Maliyeti) dinamik çekilmelidir.

---

### 30. Rollover Spread Farklarının IRR'a Yansıtılması
* **Soru:** Vade geçişinde yakın vade ile uzak vade arasındaki Calendar Spread primi taşıma maliyeti rasyosuna neden dahil edilmemiştir?
* **Defansiflik Kök Nedeni:** Her vade bağımsız değerlendirilmekte, takvim yayılma primleri carry hesabına eklenmemektedir.
* **Fırsat Odaklı Çözüm:** Uzak vade kontratının zımni faizi yakın vadeden düşükse (carry roll-down), pozisyonun otomatik sonraki aya taşınması onaylanmalıdır.

---

# 🟢 4. BÖLÜM: ÇOK VARLIKLI DAĞILIM, ENDEKS VE MAKRO SÜZGEÇLER (Sorular 31 - 40)

### 31. Ons Altın'da $TIPS < 0$ ve $DXY < SMA50$ Şartının Boğa Kaçırması
* **Soru:** ABD 10 Yıllık Reel Faizleri (TIPS) $\%1.85$ gibi yüksek seviyelerdeyken merkez bankalarının fiziki alımlarıyla Ons Altın rekor kırarken, sistemin $TIPS < 0$ kuralı yüzünden 2 yıldır tek bir Long açamaması nasıl açıklanabilir?
* **Defansiflik Kök Nedeni:** `fundamental_compass.py: L255` satırındaki geleneksel batı makro kuramı ($TIPS < 0$), jeopolitik risk ve merkez bankası rezerv talebini modelleyemediği için sistemi kör etmiştir.
* **Fırsat Odaklı Çözüm:** Jeopolitik Risk Endeksi (GPR) veya Merkez Bankaları Çeyreklik Altın Alımları verisi pozitifse, TIPS pozitif olsa dahi Ons Altın'a Long izni verilmelidir.

---

### 32. Altın / Gümüş Rasyosu (GSR > 85) Pair-Trade Bacağı
* **Soru:** GSR 85 üzerine çıktığında sistem Altın Sat / Gümüş Al spreadi önerirken, VİOP'ta Gümüş vadelisinin likiditesinin sığ olması bu işlemi neden imkansız kılmaktadır?
* **Defansiflik Kök Nedeni:** Emtia likidite barajı (Kademe 1) kontrol edilmeden pair-trade tetiklenmektedir.
* **Fırsat Odaklı Çözüm:** Gümüş vadelisinde günlük işlem hacmi $< 50M$ TL ise GSR kuralı işletilmemeli, çıplak altın yön iznine dönülmelidir.

---

### 33. CDS Priminin Artış Eğiliminde Döviz Short Yasağı
* **Soru:** Türkiye 5 Yıllık CDS primi 700'den 260 baz puana düşerken, günlük testere dalgalanmasında 20 günlük CDS eğimi hafif yukarı döndü diye döviz short işlemlerinin kesilmesi doğru mudur?
* **Defansiflik Kök Nedeni:** Kısa vadeli 20 günlük CDS trendi aşırı hassastır ve ana dezenflasyon trendindeki döviz satım fırsatlarını kilitler.
* **Fırsat Odaklı Çözüm:** 20 günlük eğim yerine CDS'in 200 günlük hareketli ortalamanın altında olması (ana ülke riski düşüş trendi) yeterli teyit kabul edilmelidir.

---

### 34. BİST 30 Endeks Vadelisinde Kompozit Finansal Temsil Hilesi
* **Soru:** `F_XU030` için tek bir sentetik FundamentalData objesi oluşturup Net Borç/FAVÖK ve F-Skor atamak, endeksin içindeki 30 şirketin dinamik rotasyonunu nasıl maskeler?
* **Defansiflik Kök Nedeni:** Endeks tek bir hisse gibi analiz edilmekte, endeks ağırlığı $\%30$ olan bankaların durumu sanayiyi gölgelemektedir.
* **Fırsat Odaklı Çözüm:** BİST 30 bileşenlerinin ağırlıklı ortalama temel puanı hesaplanmalı; ilk 5 hissenin ağırlığı $\%40$'ı aşıyorsa bu hisselerin konsolide puanı endeks yönü yapılmalıdır.

---

### 35. Sektörel Rotasyon: Sanayi vs Banka (XUSIN / XBANK) Rasyosu
* **Soru:** Endeksin yönünü belirlerken Sanayi/Banka rölatif güç rasyosunun yükselişte veya düşüşte olması neden temel pusulaya bir girdi olarak eklenmemiştir?
* **Defansiflik Kök Nedeni:** Sektörel rotasyon analizi yapılmamakta, endeks makro olarak tek parça sayılmaktadır.
* **Fırsat Odaklı Çözüm:** $XBANK / XUSIN$ rasyosu 50 günlük ortalamasının üzerindeyse banka ağırlıklı endeks Long izni onaylanmalıdır.

---

### 36. Kriz Anlarında Korelasyon Patlaması ($1.0$ Korelasyon)
* **Soru:** Sert bir piyasa şokunda hisse, döviz ve emtia arasındaki tarihsel negatif korelasyon $+1.0$'a fırladığında sistem çoklu varlık portföyünün teminatını nasıl koruyacaktır?
* **Defansiflik Kök Nedeni:** Sabit korelasyon katsayıları kullanılmakta, dinamik stres kovaryans matrisi hesaplanmamaktadır.
* **Fırsat Odaklı Çözüm:** 20 günlük canlı hareketli korelasyon $> 0.70$ olduğunda brüt portföy kaldıraç tavanı otomatik olarak $2.2x$'den $1.2x$'e düşürülmelidir.

---

### 37. Gram Altın'da Kapalıçarşı - Londra Spot Makası
* **Soru:** Türkiye'de altın ithalat kotası sebebiyle Kapalıçarşı serbest piyasa primi Londra ons çarpanına göre $\%3$ yukarıdayken VİOP vadelisinde Long açmak neden pahalı fiyattan alım tuzağıdır?
* **Defansiflik Kök Nedeni:** Kota primi takip edilmemekte, sadece vadeli fiyatına bakılmaktadır.
* **Fırsat Odaklı Çözüm:** Lokal prim $> \%1.5$ ise Gram Altın Long izni `NEUTRAL` yapılmalı, prim $\%0.5$'in altına indiğinde Long açılmalıdır.

---

### 38. Faiz Vadeli (TLREF) Spekülatif Pozisyon Yasağı
* **Soru:** TLREF vadelisinde faiz indirim döngüsünde devasa kâr potansiyeli varken sözleşmenin sadece "Hedge Amaçlı" etiketlenip yönsel al-sat yapılmaması alfa kaybı mıdır?
* **Defansiflik Kök Nedeni:** TLREF sözleşmelerine spekülatif işlem yetkisi verilmemiştir.
* **Fırsat Odaklı Çözüm:** TCMB faiz patikası aşağı yönlü kesinleştiğinde TLREF vadelisinde faiz düşüşüne spekülatif Long pozisyon açılmasına izin verilmelidir.

---

### 39. Makro Duyuru ve PPK Karar Günü Körlüğü
* **Soru:** TCMB Para Politikası Kurulu (PPK) faiz kararının açıklanacağı saat 14:00 öncesinde temel analiz motoru piyasayı neden normal seans gibi açık tutmaktadır?
* **Defansiflik Kök Nedeni:** Makro takvim entegrasyonu yoktur; şok kararlarda stop olma riski yüksektir.
* **Fırsat Odaklı Çözüm:** PPK kararından 30 dakika önce tüm varlıklarda yeni işlem açılması dondurulmalı, mevcut pozisyonların stopları daraltılmalıdır.

---

### 40. Yabancı Yatırımcı Takas Saklama Oranı Faktörü
* **Soru:** BİST yabancı takas payı yükseliş trendindeyken temel puanı zayıf olsa dahi para girişinin hisseleri yukarı taşıması pusulaya nasıl entegre edilmelidir?
* **Defansiflik Kök Nedeni:** Yabancı takas saklama değişimi bir girdi olarak kullanılmamaktadır.
* **Fırsat Odaklı Çözüm:** Son 10 günde yabancı takas payı $> \%2$ artan hisselerde F-Skor barajı 6'dan 5'e gevşetilmelidir.

---

# 🟢 5. BÖLÜM: BİLANÇO KALKANI, ENFLASYON MUHASEBESİ VE HOLDİNG/GYO KANALLARI (Sorular 41 - 50)

### 41. 24 Saatlik Bilanço Karantinasının İlk Tavanı Kaçırması
* **Soru:** Mükemmel bir bilanço açıklayan hisse ertesi gün $\%10$ tavan açtığında, 24 saatlik karantina kuralı yüzünden bu dev kâr dalgasının kaçırılması kurumsal açıdan nasıl optimize edilir?
* **Defansiflik Kök Nedeni:** `EarningsBlackoutManager` son 24 saatte bilanço gelmişse doğrudan `NEUTRAL` ve `0.0 Çarpan` vererek tüm sistemi kenara çekmektedir.
* **Fırsat Odaklı Çözüm:** Eğer yeni bilanço hem F-Skor $\ge 8$ hem de Net Kâr Büyümesi $> \%50$ üretmişse, 24 saatlik süre beklenmeden seans açılışında yarı bütçeyle ($0.5x$) tavan kırılımına katılınabilmelidir.

---

### 42. Karantina Başladığında Açık Olan Kârlı Pozisyonun Akıbeti
* **Soru:** Taşınan açık Long pozisyon varken gece bilanço açıklandığında sistem pozisyonu re'sen kapatmalı mıdır, yoksa stopunu maliyete çekip taşımalı mıdır?
* **Defansiflik Kök Nedeni:** Bilanço anında açık pozisyonun akıbeti belirsizdir; kural netleşmelidir.
* **Fırsat Odaklı Çözüm:** Kârı $\ge 1.5R$ olan pozisyonların yarısı kâr realizasyonuyla kapatılmalı, kalanı için stop seviyesi maliyete kilitlenerek bilanço şoku absorbe edilmelidir.

---

### 43. TMS 29 Parasal Kazanç / Kayıp Kaleminin F-Skorunu Bozması
* **Soru:** Enflasyon muhasebesinde net parasal pozisyon kaybı yazan şirketlerin net kârı çökse dahi operasyonel FAVÖK'ü rekor kırıyorsa F-Skorunun bunu cezalandırması nasıl önlenir?
* **Defansiflik Kök Nedeni:** F-Skor net kâr pozitifliğine bakar; parasal kayıp net kârı eksiye düşürdüğünde hisse doğrudan elenir.
* **Fırsat Odaklı Çözüm:** TMS 29 uygulanan dönemlerde F-Skorun ilk kriteri "Net Dönem Kârı" yerine "Düzeltilmiş Faaliyet Kârı (EBIT)" pozitifliğine bağlanmalıdır.

---

### 44. Özkaynak Enflasyon Düzeltmesinin ROIC ve ROE'yi Çökertmesi
* **Soru:** Duran varlıklarını yeniden değerleyip özkaynakları 5 katına çıkan bir sanayi şirketinde $ROE = Net\ Kâr / Özkaynak$ oranının $\%15$'e düşmesi hisseyi haksız yere "kârsız" mı gösterir?
* **Defansiflik Kök Nedeni:** Payda devasa büyüdüğü için kârlılık rasyoları yapay olarak erir.
* **Fırsat Odaklı Çözüm:** Kârlılık rasyoları ödenmiş sermaye ve çekirdek operasyonel sermaye üzerinden normalize edilerek hesaplanmalıdır.

---

### 45. Holding Kanalı A1: Net Aktif Değeri (NAD) $+1.5\sigma$ İskonto Tuzağı
* **Soru:** Holdingin iştirakleri borsada çok hızlı ralli yaptığı için holding iskontosu tarihsel medyanın üzerine çıktığında Long yönün yasaklanması ralli yapan holdingi kaçırır mı?
* **Defansiflik Kök Nedeni:** `holding_metrics.is_expensive_vs_history` kontrolü iskontonun daraldığı güçlü boğa dönemlerinde Long iznini toptan kesmektedir.
* **Fırsat Odaklı Çözüm:** İştiraklerin toplam piyasa değeri son 1 ayda $> \%20$ artmışsa, iskonto daralsa dahi hisseye momentum Long izni verilmelidir.

---

### 46. Holding Solo Temettü Akışının Faiz Giderini Karşılama Sıklığı
* **Soru:** İştirakler temettüyü yılda bir kez (Nisan ayında) öderken, holdingin faiz giderinin her çeyrek yazılması diğer 3 çeyrekte nakit akışı karşılama rasyosunu hatalı negatif yapar mı?
* **Defansiflik Kök Nedeni:** Çeyreklik bazda bakıldığında temettü geliri olmayan 9 ay boyunca holding "faizini ödeyemiyor" görünmektedir.
* **Fırsat Odaklı Çözüm:** İştirak temettü akışı çeyreklik değil, son 4 çeyreğin kümülatif toplamı (Trailing 12 Months - TTM) olarak hesaplanmalıdır.

---

### 47. GYO Kanalı A2: Değerlemeden Arındırılmış FFO Negatifliği Yanılgısı
* **Soru:** Büyük bir AVM veya konut projesi inşaat aşamasında olan ve henüz teslimat faturası kesmeyen bir GYO'da değerleme kârı düşüldüğünde FFO negatif çıkarsa bu şirket gerçekten batık mıdır?
* **Defansiflik Kök Nedeni:** FFO sadece kira gelirine odaklanır; proje geliştirici GYO'ların ön satış nakit girişlerini göremez.
* **Fırsat Odaklı Çözüm:** Müşteri Sözleşmelerinden Doğan Ön Satış Nakit Avansları FFO formülüne nakit giriş olarak eklenmelidir.

---

### 48. GYO Portföy Kaldıraç Sınırının (%40) Şişirilmiş Ekspertizle Bozulması
* **Soru:** Gayrimenkul portföy ekspertiz değeri enflasyonla devasa artırıldığında borçluluk oranı ($\frac{Net\ Borç}{Portföy}$) yapay olarak düşük çıkıp riskli bir GYO'yu güvenli gösterebilir mi?
* **Defansiflik Kök Nedeni:** Ekspertiz raporlarının gerçeğe uygunluğu denetlenmemektedir.
* **Fırsat Odaklı Çözüm:** Kısa Vadeli Finansal Borç / Yıllık Kira Geliri rasyosu ek bir likidite kalkanı olarak devreye alınmalıdır.

---

### 49. Kanal A1 ve A2'nin Canlı Testte Backtest Eksikliği
* **Soru:** Holding ve GYO kanalları yeni kodlandığı için geçmiş 3 yıllık backtest veritabanında test edilmemiş olması canlı piyasada sürpriz yaratır mı?
* **Defansiflik Kök Nedeni:** Geçmiş veri setinde sadece standart Kanal A ve B test edilmiştir.
* **Fırsat Odaklı Çözüm:** SAHOL ve EKGYO için 3 yıllık tarihsel NAD ve FFO zaman serisi indirilip simülasyon tamamlanmalıdır.

---

### 50. Temel Yön İzninin Zaman Aşımı (Signal Expiry / Staleness)
* **Soru:** Temel pusuladan çıkan `ONLY_LONG` izninin üzerinden 45 gün geçmesine rağmen teknik kırılım gelmemişse, bu izin hala ilk günkü kadar taze midir?
* **Defansiflik Kök Nedeni:** Kod tabanında yön izninin bir son kullanma tarihi (Time-to-Live / TTL) yoktur; bilanço eskiyebilir.
* **Fırsat Odaklı Çözüm:** Bilanço tarihinden itibaren 60 gün içinde teknik kırılım gerçekleşmemişse bütçe çarpanı otomatik olarak $1.0x$'den $0.5x$'e düşürülmelidir.

---

Tüm bu 50 sorunun yanıtları ve parametre kalibrasyonları uygulandığında, Temel Karar Motoru **sistemi kilitleyen bir pranga olmaktan çıkıp**, piyasa koşullarına göre esneyen ve **alfa üreten dinamik bir yön pusulasına** dönüşecektir.
