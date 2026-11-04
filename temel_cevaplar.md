# TEMEL ANALİZ MOTORU 50 SORULUK DENETİM VE KALİBRASYON REÇETESİ YANITLARI
**Hedef Motor:** `FundamentalCompass` (`src/strategy/fundamental_compass.py`), `MetricsCalculator` (`src/strategy/metrics_calculator.py`)  
**Tarih:** 2026-10-23  

---

### 🟢 1. Bölüm: Bankacılık Kanalı (Kanal B) ve Net Faiz Marjı (NIM) Çıkmazı (Sorular 1 - 10)
* **Daralan NIM Kuralı Prangası (Soru 1):** TCMB faiz artırırken mevduat faizleri hemen yükselip kredi getirileri gecikmeli geldiği için bankalarda çeyreklik Net Faiz Marjı daralmıştır ($\Delta NIM < 0$). Kodda yer alan `if nim_change < 0: return ONLY_SHORT` satırı, borsa rallisinde Akbank ve Garanti'de kesintisiz ONLY_SHORT vererek sistemi ralli boyunca kilitlemiştir.  
  * **Çözüm:** Bankanın Özkaynak Kârlılığı ($RoAE$) enflasyonun üzerindeyse veya Komisyon Gelirleri Büyümesi $> \%50$ ise, $0.5x$ bütçe çarpanıyla `ONLY_LONG (Tier 2)` iznine geçilmelidir.
* **Aşırı Katı SYR ve Çekirdek Sermaye Barajı (Sorular 2-3):** Bankalarda aranan $\%16$ SYR ve $\%12$ Tier 1 sınırı, krediye dönüştürüp kâr yazan özel bankaları (Garanti, Akbank, İş) dışlamaktadır.  
  * **Çözüm:** Eşikler $SYR \ge \%14.0$ ve Tier 1 $\ge \%10.5$ seviyesine esnetilmelidir.
* **Ücret/Komisyon ve Değerleme İskontosu (Sorular 4-5):** Net kârın $\%40$'ına ulaşan komisyon gelirleri ve $\%50-\%60$ $PD/DD$ iskontoları koda girdi yapılmamıştır.  
  * **Çözüm:** $PD/DD \le 0.75$ olan kelepir bankalara NIM daralsa dahi $0.5x$ çarpanla Long izni verilmelidir.
* **Aktif Kalitesi ve NPL Kalkanı (Soru 6):** Takipteki Krediler Oranı ($NPL < \%2.0$) ve karşılık oranı $\%80$ olan defansif bankalara pozitif katsayı verilmemektedir.  
  * **Çözüm:** $NPL < \%2.0$ olan bankalara "Aktif Kalite Bonusu" verilip çarpan $1.0x$'e çıkarılmalıdır.
* **Geleceği Gören (Forward-Looking) NIM (Soru 7):** Piyasa faiz indirimlerini 3-6 ay önceden fiyatlarken motor geçmiş bilançoya bakmaktadır.  
  * **Çözüm:** 2 Yıllık Gösterge Tahvil faizi $SMA_{50}$ altına indiğinde "NIM Genişleme Beklentisi" tetiklenip Long kanalı açılmalıdır.
* **TCMB Regülasyon Riski ve Menkul Kıymet Tesis Oranı (Soru 8):** Regülasyon baskısı bankaları kilitlerken serbestleşme dönemleri ödüllendirilmemektedir.  
  * **Çözüm:** Menkul kıymet tesis zorunluluğu gevşetildiğinde banka bütçesi $1.25x$'e çıkarılmalıdır.
* **Mevduat / Kredi Makası Dinamiği (Soru 9):** TL Kredi/Mevduat oranı $\%90$'ın altında olan likit bankalar dışlanmaktadır.  
  * **Çözüm:** K/M $< \%95$ olan bankalar faiz şokuna dayanıklı kabul edilmelidir.
* **Kamu vs Özel Banka Ayrışması (Soru 10):** Kamu bankalarının görev zararı ve sermaye enjeksiyonları özel bankalarla aynı kuralla ölçülemez.  
  * **Çözüm:** Kamu ve özel bankalar için farklı rasyo katsayıları tanımlanmalıdır.

---

### 🟢 2. Bölüm: Reel Sektör (Kanal A) Bilanço Rasyoları ve Prangalar (Sorular 11 - 20)
* **Piotroski F-Skoru ($F \ge 7$) Elitistliği (Soru 11):** BİST'te 9 üzerinden 7 puan alabilen şirket sayısı kısıtlı olduğundan fırsat evreni $\%90$ daralmaktadır.  
  * **Çözüm:** $F \ge 5$ alan şirketlere $0.5x$ çarpanla izin verilmeli; $\Delta F \ge +2$ artış varsa $1.0x$ yapılmalıdır.
* **Altman Z-Skoru ($Z \ge 2.60$) ve Borç Kısıtı (Sorular 13-14):** THY, Türk Telekom gibi yatırımlı devler gri bölgede ($Z=2.10-2.40$) kaldığı için elenmektedir. Ayrıca Net Borç / FAVÖK $> 3.5$ olan ihracatçı şirketler zorla Short'a itilmektedir.  
  * **Çözüm:** Sektörel medyan Z-Skor referansı getirilmeli; İhracat Oranı $> \%40$ olan borçlu şirketler Short değil `NEUTRAL` yapılmalıdır.
* **%50 Faiz Ortamında $ROIC > WACC$ Felci (Soru 16):** $\%50$ politika faizinde $WACC = \%58$ çıktığı için Türkiye'de hiçbir şirket EVA üretemez görünmekte ve sistem kurumaktadır.  
  * **Çözüm:** $WACC$ hesabındaki risksiz faiz, 10 yıllık reel tahvil getirisi (enflasyondan arındırılmış reel faiz: $\%15-\%20$) üzerinden revize edilmelidir.
* **Cari Oran Katılığı (Soru 12):** Tedarik zinciri güçlü dev perakendeciler (BIMAS, MGROS) negatif işletme sermayesiyle çalıştığı için elenmektedir.  
  * **Çözüm:** Perakende sektöründe Negatif Çalışma Sermayesi bir güç olarak kodlanmalıdır.
* **Faiz Karşılama Oranı (ICR) Kriteri (Soru 15):** Yüksek faizde $EBIT / Faiz > 3.0$ bulmak imkansızlaşmıştır.  
  * **Çözüm:** ICR eşiği $1.8x$'e çekilmeli; nakit akışı güçlüyse tolere edilmelidir.
* **FAVÖK Marjı Aşınması Kuralı (Soru 17):** Ciro rekoru kıran ancak marjı 100 bps daralan şirketlerin dışlanması engellenmelidir.  
  * **Çözüm:** FAVÖK büyümesi enflasyonu aşıyorsa marj daralması göz ardı edilmelidir.
* **Döviz Pozisyonu Açığı (Soru 18):** Doğal hedge'e sahip ihracatçıların net döviz açığı elenmemelidir.  
  * **Çözüm:** İhracat geliri döviz borcunu karşılıyorsa döviz riski iptal edilmelidir.
* **İşletme Sermayesi İhtiyacı (NWC) Baskısı (Soru 19):** Enflasyonda stok tutan şirketler ödüllendirilmelidir.  
  * **Çözüm:** Stok devir hızı yüksek şirketlerde NWC artışı pozitif skorlanmalıdır.
* **Ar-Ge ve Yatırım Harcamaları (Capex) (Soru 20):** Büyüme yatırımı yapan şirketlerin nakit akışı negatif olsa bile elenmemesi sağlanmalıdır.  
  * **Çözüm:** Büyüme Capex'i ile bakım Capex'i ayrıştırılmalıdır.

---

### 🟢 3. Bölüm: Taşıma Maliyeti (Carry / IRR) ve Arbitraj Engelleri (Sorular 21 - 30)
* **Fahiş Contango (%2.5 / 250 bps) Engeli (Soru 21):** Güçlü boğa trendlerinde vadeli kontratlar doğal olarak primli işlem görürken sabit 250 bps sınırı Long pozisyonu tamamen yasaklamaktadır.  
  * **Çözüm:** Sabit sınır yerine hissenin tarihsel basis volatilitesinin 2 standart sapması (Bollinger Basis $+2\sigma$) dinamik eşik yapılmalıdır.
* **Temettü Düzeltmeli IRR ve Arbitraj (Sorular 22 & 25):** Temettü verimi düşülmeden hesaplanan Zımni Repo ($IRR$) yapay contango algısı yaratmaktadır.  
  * **Çözüm:** $F_{teorik} = (S_0 - PV(\text{Temettü})) \cdot e^{rt}$ işletilmeli; contango durumunda yön kilitlenirken nakit tamponu ile risksiz Cash-and-Carry Arbitrajı tetiklenmelidir.
* **Vade Sonu Yıllıklandırma Sapması (Soru 24):** Vadeye $<5$ gün kala $365/t$ çarpanı faizi $\%200$'lere fırlatmaktadır.  
  * **Çözüm:** Vadeye 7 iş günü kala Cost of Carry kontrolü bir sonraki aktif vadeye (Next Month) devredilmelidir.
* **Aşırı Backwardation (Soru 23):** Düşüş dönemlerinde spotun altına inen vadeli fiyatlarda Short yasağı kalkmalıdır.  
  * **Çözüm:** Aşırı backwardation görüldüğünde Spot Al - Vadeli Sat Reverse Cash-and-Carry devreye alınmalıdır.
* **Kambiyo ve Faiz Makası (Soru 26):** Dolar/TL vadelisindeki basis TCMB faiziyle birebir kalibre edilmelidir.
* **Roll-Over (Vade Taşıma) Maliyeti (Soru 27):** Vade geçişinde spread zararı yaşamamak için pozisyonlar son 3 güne kalmadan taşınmalıdır.
* **Piyasa Yapıcı Likidite Kalkanı (Soru 28):** Vadeli tahtadaki spread 5 kademeden genişse işlem açılmamalıdır.
* **Teminat Tamamlama (Margin Call) Faiz Maliyeti (Soru 29):** Ters pozisyonda teminat tamamlama maliyeti stop kararına dahil edilmelidir.
* **Statik Faiz Yerine Gecelik O/N Oranı (Soru 30):** Modeldeki faiz sabit değil, canlı Akbank ALE gecelik repo faizi olmalıdır.

---

### 🟢 4. Bölüm: Çok Varlıklı Dağılım, Endeks ve Makro Süzgeçler (Sorular 31 - 40)
* **Ons Altın $TIPS < 0$ Kuralının Boğa Kaçırması (Soru 31):** ABD Reel Faizleri ($TIPS$) yüksekken merkez bankası alımlarıyla altın rekor kırarken, $TIPS < 0$ şartı yüzünden 2 yıldır tek bir Long açılamamıştır.  
  * **Çözüm:** Jeopolitik Risk Endeksi (GPR) veya Merkez Bankası Altın Alımları pozitifse TIPS şartı esnetilmelidir.
* **Endeks Vadelisi ($F\_XU030$) Sentetik Temsil Hilesi (Soru 34):** Endekse tek bir hisse gibi bakmak içindeki rotasyonu maskelemektedir.  
  * **Çözüm:** BİST 30 bileşenlerinin piyasa değeri ağırlıklı temel puanı hesaplanmalıdır.
* **CDS Eğimi Esnekliği (Soru 33):** 20 günlük hassas CDS eğimi yerine CDS'in 200 günlük hareketli ortalamasının altında olması (ana ülke riski düşüş trendi) yeterli teyit sayılmalıdır.
* **Dolar/TL ve Emtia Korelasyonu (Soru 32):** Dolar/TL yatay seyrederken emtialardaki küresel süper-döngü yön pusulasına bağlanmalıdır.
* **Yabancı Takas Oranı Eğimi (Soru 35):** Yabancı takası $\%30$'dan $\%40$'a çıkarken sisteme ek $1.25x$ çarpan verilmelidir.
* **Sektörel Rotasyon Motoru (Soru 36):** Para Sanayi'den Banka'ya geçerken sistem geride kalan sektörü açığa satmaya kalkmamalıdır.
* **TCMB Faiz Patikası ve Enflasyon Beklentisi (Soru 37):** Piyasa Katılımcıları Anketi 12 aylık TÜFE beklentisi modele entegre edilmelidir.
* **Brent Petrol ve Taşımacılık / Havacılık (Soru 38):** Petrol düştüğünde THYAO ve PGSUS'a otomatik pozitif temel destek verilmelidir.
* **Demir Çelik ve Hurda Fiyatı (Soru 39):** EREGL/KRDMD için HRC ve Hurda Çelik makası takip edilmelidir.
* **Elektrik ve Doğalgaz Sanayi Tarifeleri (Soru 40):** Enerji maliyet artışları marj hassasiyetine göre skorlanmalıdır.

---

### 🟢 5. Bölüm: Bilanço Kalkanı, Enflasyon Muhasebesi ve Holding/GYO Kanalları (Sorular 41 - 50)
* **24 Saatlik Karantina Esnekliği (Soru 41):** Tavan açan harika bilançolarda 24 saat bekleme kuralı ilk kâr dalgasını kaçırmaktadır.  
  * **Çözüm:** Yeni bilanço $F \ge 8$ ve Kâr Büyümesi $> \%50$ üretmişse seans açılışında $0.5x$ yarı bütçeyle tavan kırılımına girilmelidir.
* **TMS 29 Enflasyon Muhasebesi Kalibrasyonu (Sorular 43-44):** Parasal kayıp yazan ancak FAVÖK rekoru kıran şirketler net kâr yüzünden F-Skorunda elenmektedir.  
  * **Çözüm:** TMS 29 dönemlerinde net kâr yerine Faaliyet Nakit Akışı ($CFO$) ve EBIT pozitifliği baz alınmalıdır.
* **Holding (A1) ve GYO (A2) Kanalları (Sorular 45-48):** Holdinglerde Net Aktif Değeri (NAD) iskontosu, GYO'larda ise değerlemeden arındırılmış FFO (Funds From Operations) ve birim pay değeri iskontosu özel kanal kuralları olarak işletilmelidir.
* **Bilanço Sızıntısı ve Fiyat Hareketi (Soru 42):** Bilanço öncesi hisse %15 yükselmişse "Beklenti Bitti" realizasyonu algılanmalıdır.
* **Vergi Dairesi vs SPK Bilanço Farkı (Soru 49):** Geçici vergi beyannamelerindeki ciro patlaması SPK bilançosu öncesi öncü sinyal yapılmalıdır.
* **Yön İzni Zaman Aşımı (TTL) (Soru 50):** 60 gün boyunca teknik kırılım gelmeyen temel yön izinlerinin bütçe çarpanı otomatik olarak $1.0x$'den $0.5x$'e düşürülerek bayat sinyal riski engellenmelidir.
