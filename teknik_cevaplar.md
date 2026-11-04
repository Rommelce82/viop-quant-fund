# TEKNİK ANALİZ VE İCRA MOTORU (33 KURAL) 50 SORULUK DENETİM VE KALİBRASYON REÇETESİ YANITLARI
**Hedef Motor:** `TechnicalExecutioner` (`src/strategy/technical_executioner.py`), `PositionManager` (`src/strategy/position_manager.py`), `Indicators` (`src/strategy/indicators.py`)  
**Tarih:** 2026-10-23  

---

### 🟢 1. Bölüm: Rejim Tespiti, ADX Testere Kalkanı ve Gösterge Sıkışması (Sorular 1 - 10)
* **ADX < 20 Testere Barajı Prangası (Soru 1):** Konsolidasyon patlamalarının en yüksek momentumlu başlangıç anında ADX doğal olarak 14-18 bandında dip yapmaktadır. Kodda yer alan `if latest_adx < 20.0: return REJECT_TESTERE_ADX_DUSUK` satırı, trendin ilk %30-%40'lık en güvenli kâr dalgasını kaçırmaktadır.  
  * **Çözüm:** Donchian kırılımı hacim patlamasıyla ($Volume \ge 1.4 \times SMA20$) destekleniyorsa ve ADX'in 1. türevi pozitifse ($\frac{d(ADX)}{dt} > 0$), ADX alt tabanı **$15.0$** seviyesine esnetilerek trendler en dipten yakalanmalıdır.
* **Katı ADX Eğim Şartı ($ADX_t > ADX_{t-1}$) (Soru 2):** Güçlü bir ralli sırasında hisse tek bir saat dinlendiğinde ADX 0.1 puan gevşemekte ve motor anında `RANGE_BOUND` rejimine geçerek kırılımları kilitlemektedir.  
  * **Çözüm:** Eğim şartı tek bar yerine 3 barlık eğim ($ADX_t \ge ADX_{t-3} - 0.5$) yapılmalı; $ADX \ge 25$ ise eğim şartı aranmaksızın trend rejimi korunmalıdır.
* **ADX > 50 Trend Yorgunluğu Kısıtı (Soru 3):** Türk hisseleri döviz şoku veya enflasyonist rallilerde ADX 60-70 bandına fırlayıp günlerce tavan serisi yaparken sistemin yeni girişleri tamamen yasaklaması kâr potansiyelini budamaktadır.  
  * **Çözüm:** $ADX > 50$ durumunda işlem tamamen yasaklanmamalı; işlem bütçesi $\%50$ küçültülerek ($0.5x$ bütçe) ve stop mesafesi daraltılarak parabolik dalganın devamı kovalanmalıdır.
* **Aşırı Volatilite ($ATR / Close > \%3$) Barajı (Soru 4):** B-Tarzı kırılımlar doğası gereği uzun mumlarla başlar; bu filtre hisselerdeki en kârlı kırılım anında sistemi korkutup kenara çekmektedir.  
  * **Çözüm:** Eşik hisselerde $\%4.5$'e çekilmeli; yüksek volatilitede işlem iptal edilmek yerine stop mesafesi daraltılıp lot küçültülmelidir.
* **DIOSC Sinyal Kesişimi Gecikmesi (Soru 5):** `DIOSC < SMA(9, DIOSC)` filtresi 9 periyotluk gecikme nedeniyle kırılım geldiğinde henüz yukarı dönmediği için işlemi haksız yere iptal etmektedir.  
  * **Çözüm:** SMA(9) yerine 5 periyotluk `EMA(5, DIOSC)` kullanılmalı veya $DIOSC > 0$ olması tek başına yeterli teyit kabul edilmelidir.
* **Günlük SMA(100) Mutlak Trend Filtresinin Katılığı (Soru 6):** 6 aylık düşüşten sonra dipte çift dip ile fırlayan hisselerde SMA100'e varana kadar trendin yarısı bitmektedir.  
  * **Çözüm:** Hisse 20 günlük EMA'sının üzerine çıkmış ve $EMA20 > EMA50$ olmuşsa $0.5x$ bütçe ile "Erken Dip Dönüşü" Long izni verilmelidir.
* **Fiyatın SMA20'den %15 Gerilme Filtresi (Soru 7):** Ralli günlerinde fiyat saatlik SMA20'den hızla kopar; sistem bunu "aşırı gerilme" sanarak alımı kilitler.  
  * **Çözüm:** Bu kontrol saatlik SMA20 yerine Günlük SMA50 üzerinden yapılmalı; RSI < 80 ve hacim güçlüyse kırılım veto edilmemelidir.
* **Çoklu Zaman Dilimi (Daily vs 60m) Zamanlama Uyuşmazlığı (Soru 8):** Günlük SMA100 gün sonunda kesinleştiği için gün içi kırılımlar ertesi güne kadar onay alamamaktadır.  
  * **Çözüm:** Gün içi canlı barın son fiyatı da dahil edilerek kümülatif güncellenen `dynamic_daily_sma100` kullanılmalıdır.
* **VWAP (Hacim Ağırlıklı Ortalama Fiyat) Eksikliği (Soru 9):** Fiyat Donchian kırdığı halde seanslık VWAP altındaysa kurumsal alıcı yoktur; sistem bunu ayırt edememektedir.  
  * **Çözüm:** Seanslık Rolling VWAP eklenmeli; $Close > VWAP$ şartı kırılımda teyit olarak aranmalıdır.
* **Sabit 14 Periyotluk ATR Çıkmazı (Soru 10):** Ani volatilite patlamalarında ATR(14) gecikmeli kaldığı için pozisyon ertesi barda iğne ucuyla stop olmaktadır.  
  * **Çözüm:** Normal zamanlarda ATR(14), volatilite anında ATR(5) ağırlıklı dinamik bileşik ATR ($0.7 \times ATR_5 + 0.3 \times ATR_{14}$) işletilmelidir.

---

### 🟢 2. Bölüm: B-Tarzı Kırılım ve Hacim Patlaması (1.8x Hacim Çıkmazı) (Sorular 11 - 20)
* **Endekste ($F\_XU030$) 1.8x Hacim Barajının İmkansızlığı (Soru 11):** BIST 30 endeks vadelisinde saatlik hacim yüksek taban hacimle sürekli aktığı için tek bir saatlik barda $1.8 \times SMA20$ patlaması neredeyse hiç oluşmaz. Bu kural endekste 3 yıl boyunca 0 işlem açılmasına neden olmuştur.  
  * **Çözüm:** Hacim çarpanı varlık sınıfına göre dinamikleştirilmelidir:
    * **Endeks VİOP (`F_XU030`):** **$1.15 \times SMA20$**
    * **Hisse VİOP:** **$1.40 \times SMA20$**
    * **Emtia/Döviz VİOP:** **$1.20 \times SMA20$**
* **Donchian 20-Bar Kanalının Sadece Zirve Kırılımlarını Araması (Soru 12):** Sistem sadece 20 barın tepesini kıran barlarda işleme girer; trend boyunca ortalamalara yapılan geri çekilmeleri (Pullback / Retest) tamamen yok sayar.  
  * **Çözüm:** Sisteme **"Pullback / Keltner Retest"** modu eklenmeli; trend rejiminde EMA20'ye değip yukarı dönen barlarda 1.0R hedefli fırsat alımları açılmalıdır.
* **Shift(1) Lookahead Korumasının Kapanış Barında Yarattığı Slippage (Soru 13):** Saatlik bar kapanışını beklemek, bar içinde %4 fırlamış hissede en tepeden mal aldırıp stop mesafesini büyütmektedir.  
  * **Çözüm:** Bar kapanışı beklenmek yerine Donchian seviyesine `STOP BUY` koşullu emri konulmalı; kırıldığı milisaniyede trene binilmelidir.
* **Düşüş Kırılımlarında (Short) Hacim Patlaması Arama Hatası (Soru 14):** Borsada panik düşüşleri likidite çekilmesi ve düşük hacimli boşluklarla gerçekleşir; sistemin Short için de 1.8x hacim araması Short fırsatlarını felç etmektedir.  
  * **Çözüm:** Short işlemlerde hacim şartı **$1.0 \times SMA20$** (ortalama hacim yeterli) seviyesine çekilmelidir.
* **Relative Volume (RVol) Eksikliği (Soru 15):** Sabah 10:30 hacmi ile öğle 13:00 hacmini aynı SMA ile kıyaslamak öğle kırılımlarını haksız yere eler.  
  * **Çözüm:** Gün içi zamana duyarlı RVol (`Relative Volume by Time of Day`) kullanılmalıdır.
* **Donchian Periyodunun Varlık Tipine Göre Değişmemesi (Soru 16):** 20 saatlik periyot hisselerde 2.2 seans günüyken, 24 saat işlem gören ons altında 1 günden azdır.  
  * **Çözüm:** Endekste 24 bar, hisselerde 16 bar, emtiada 30 bar olarak yapılandırılmalıdır.
* **Bollinger Squeeze Teyidi Olmaması (Soru 17):** Kanal çok genişken gelen kırılımlar tükeniş alımı olabilir.  
  * **Çözüm:** Bollinger Bandı Keltner Kanalının içine girdiğinde (`Squeeze`) gelen ilk kırılım $1.5x$ bütçeyle agresif yakalanmalıdır.
* **Çift Bar Teyidi ve İki Aşamalı Giriş (Soru 18):** Tek barlık sahte kırılımların (fakeout) yarattığı kayıplar engellenmelidir.  
  * **Çözüm:** Kırılım barında $\%50$ lot açılmalı, sonraki bar kırılım üstünde kalırsa kalan $\%50$ eklenmelidir.
* **Düşük Hacimli Konsolidasyon Kırılımlarının Dışlanması (Soru 19):** Satıcılar çekildiğinde hisse düşük hacimle tavana kopabilir; sistem bunu hacimsiz diye reddeder.  
  * **Çözüm:** Hacim mutlak veto nedeni olmaktan çıkarılmalı; hacim zayıfsa lot %30 azaltılarak işleme girilmelidir.
* **Kırılım Seviyesinin Yüzdesel Marjı (Breakout Buffer) (Soru 20):** 1 kademelik taşmalar sahte kırılımlara ve erken stoplara yol açmaktadır.  
  * **Çözüm:** Kırılım şartı $Current\_Price > Prev\_Don\_High + (0.1 \times ATR)$ olarak güncellenmelidir.

---

### 🟢 3. Bölüm: Mikro-Yapı Filtreleri (Fitil, Gap, Inside Bar, 09:30-10:30 Engeli) (Sorular 21 - 30)
* **Üst Fitil (Upper Wick) > %40 Kuralı ve Kurumsal Boğa Mumlarının Reddedilmesi (Soru 21):** %5'lik devasa boğa gövdesinde küçük bir geri çekilme fitil oranını %40'ın üzerine çıkardığında alımın veto edilmesi en güçlü kurumsal alımları çöpe atmaktadır.  
  * **Çözüm:** Eğer barın gövdesi ($Close - Open$) ortalama bar gövdesinin 2 katından büyükse (`Expansion Bar`), üst fitil $\%55$'e kadar tolere edilmelidir.
* **Alt Fitil (Lower Wick) > %40 Kuralı ve Short İptalleri (Soru 22):** Ayı kırılımlarında dipten gelen küçük tepkiler çekiç fitili yaratsa da ana trend düşüş yönündedir.  
  * **Çözüm:** Alt fitil toleransı $\%50$'ye çıkarılmalı ve Temel Pusula `ONLY_SHORT` ise fitil kısıtlaması esnetilmelidir.
* **Gap > %2 Filtresinin (REJECT_GAP_LARGE) Kaçış Boşluklarını Engellemesi (Soru 23):** İyi bilanço veya küresel coşkuyla %2.5 gap ile açılıp tavan çeken günlerde sistem kenarda kalmaktadır.  
  * **Çözüm:** Gap yönünde hacim rekoru varsa ve ilk 1 saatte gap dolmuyorsa, bu bir "Kaçış Boşluğu"dur (Breakaway Gap) ve $0.75x$ bütçeyle derhal girilmelidir.
* **Saat 09:30 - 10:30 Açılış Çalkantısı Filtresi (REJECT_TIME_OPENING) (Soru 24):** Günün en sert trend hareketleri açılışın ilk 30 dakikasında başlar; 1 saat beklemek fiyat hedefine vardıktan sonra trene bakmak demektir.  
  * **Çözüm:** Blokaj aralığı **09:30 - 10:05 (ilk 35 dakika - spot açılış sindirilene kadar)** olarak daraltılmalı; 10:05'ten itibaren kırılımlar icra edilmelidir.
* **Inside Bar Mutlak Vetosu (REJECT_INSIDE_BAR) (Soru 25):** İç barlar daralan üçgen/flama sıkışmasıdır; Ali Perşembe'nin "Inside Bar Harlot" stratejisi kırılma yönüne agresif emir konulmasını emreder.  
  * **Çözüm:** İç bar görüldüğünde işlem iptal edilmemeli; bir sonraki barda iç barın en yükseği aşılırsa piyasa emriyle Long açan tetikleyici kurulmalıdır.
* **KAP Haberi Filtresi (REJECT_KAP_NEWS) (Soru 26):** İhale kazanımı veya pay geri alımı KAP'ı geldiğinde sistemin haberi risk görüp girişi yasaklaması kârı engeller.  
  * **Çözüm:** Haber kategorize edilmeli; pozitif operasyonel haberlerde veto kaldırılmalı, sadece belirsizlik/dava haberlerinde veto uygulanmalıdır.
* **Cuma 17:45 Kapanış Kuralının (FRIDAY_CLOSE_EXIT) Erken Çıkışları (Soru 27):** Cuma açılan ve 0.8R kârda olan pozisyon sırf hafta sonu riski yüzünden kapatılmakta, Pazartesi ralli kârı kaçmaktadır.  
  * **Çözüm:** Kapatma barajı $0.0R$ (yani zarardaysa kapat) yapılmalı; pozisyon kârda ise stop maliyete çekilerek hafta sonuna taşınmalıdır.
* **VİOP Akşam Seansı (18:15 - 19:00) İhmali (Soru 28):** Küresel verilerle akşam seansında sert hareketler olurken saatlik barların sadece gündüze göre hesaplanması risk yaratır.  
  * **Çözüm:** Akşam seansı verisi sentetik bir bar olarak sisteme eklenmeli ve risk çarpanı %50'ye çekilmelidir.
* **Spread ve Tahta Derinliği Filtresi Eksikliği (Soru 29):** Sığ saatlerde 10 kademe spread varken piyasa emri göndermek 0.5R kayma zararı üretir.  
  * **Çözüm:** `Spread <= 0.05%` kuralı eklenmeli; spread açıksa pasif limit emir iletilmelidir.
* **Genişleme Barı (Expansion Bar) Momentum Ödüllendirmesi (Soru 30):** Bar boyu son 20 saatin 3 katına ulaştığında sistem bunu ödüllendirmez.  
  * **Çözüm:** $Bar\_Range > 2.5 \times ATR$ olan barlarda risk bütçesi $1.25x$'e çıkarılmalıdır.

---

### 🟢 4. Bölüm: Risk Yönetimi, Zaman Stopu ve Çıkış Otoritesi (Sorular 31 - 40)
* **12-Bar Zaman Stopunun (TIME_STOP_BARS = 12) Kârlı Pozisyonları Katletmesi (Soru 31):** THYAO backtestinde 14 işlemden 11'i tam trende girecekken 12 saat (1.5 gün) dolduğu için `TIME_STOP_EXIT` ile kapatılmış ve kazanma oranı %28'e düşmüştür. VİOP swing trendleri için 1.5 gün gülünç derecede kısadır.  
  * **Çözüm:** Zaman stopu 12 saatten **30 saate (yaklaşık 4-5 işlem günü)** çıkarılmalıdır. Fiyat giriş maliyetinin üzerindeyse ($PnL > 0$), zaman stopu tamamen devre dışı bırakılmalıdır.
* **Kademeli Çıkışta (%50 at 1.5R) Pozisyonun Erken Budanması (Soru 32):** 1.5R kârda pozisyonun yarısının satılması kazanan işlemlerin ortalama getirisini aşağı çekmektedir.  
  * **Çözüm:** Kademeli çıkış ilk hedefi **$2.0R$** seviyesine ötelenmeli; kapatılan lot oranı $\%50$ yerine $\%33$ yapılmalı, kalan $\%67$ trend boyunca sürülmelidir.
* **Chandelier Exit Çarpanının Parabolik Durumda 1.5x'e Aşırı Hızlı Daraltılması (Soru 33):** 1.5 ATR çok dar bir mesafedir; normal bir gün içi dalgalanma kârlı pozisyonu erken stop ettirir.  
  * **Çözüm:** Stop mesafesi aniden 1.5x'e düşürülmemeli; bar başına kademeli olarak ($2.5 \rightarrow 2.2 \rightarrow 2.0$) daraltılmalıdır.
* **Minimum R/K >= 2.5 Barajının Endekste İmkânsız Hedefler Doğurması (Soru 34):** Stop mesafesi 2.0x ATR olan endeks kontratında 2.5 R/K hedefi, endeksin tek dalgada %5-%6 (500-600 puan) gitmesini zorunlu kılar; bu durum endekste işlem açılmasını tamamen engellemiştir.  
  * **Çözüm:** R/K barajı sözleşme bazlı esnetilmelidir:
    * **Hisse Kontratları:** Minimum **$2.0 R/K$**
    * **Endeks Kontratı (`F_XU030`):** Minimum **$1.5 R/K$**
* **Stopun Maliyete (Tapi) Çekilmesinin Whipsaw / Retest Tuzağı (Soru 35):** Stopun doğrudan giriş fiyatına çekilmesi eski direncin yeni destek olarak test edilmesi payını sıfırlamakta ve sıfır kârla stop ettirmektedir.  
  * **Çözüm:** Stop tam maliyet noktasına değil, $Entry - (0.5 \times ATR)$ seviyesine çekilerek retest payı bırakılmalıdır.
* **İlk Stop Mesafesinin (2.0x ATR) Lot Sayısını Aşırı Küçültmesi (Soru 36):** Volatilitede 2.0x ATR stop mesafesi o kadar genişler ki 100K bütçeyle açılabilecek lot sayısı 0'a düşer.  
  * **Çözüm:** Eğer kırılım barının en düşüğü 2.0 ATR'den daha yakınsa, ilk stop doğrudan `Kırılım Barının En Düşüğü - 2 kademe` yapılmalı ve lot sayısı artırılmalıdır.
* **Sabit Fiyatlı Kâr Al (TP) Hedefinin Trendi Kaçırması (Soru 37):** Peşin TP koymak hisse %100 gittiğinde 2.5R'da trendden inmeye sebep olur.  
  * **Çözüm:** Sabit TP sadece ilk %33 lot için uygulanmalı; ana pozisyon Chandelier dinamik iz süren stop kırılana kadar taşınmalıdır.
* **Ters Yönlü Sinyal Çıkışı (Reverse Exit) Bulunmaması (Soru 38):** Long taşırken pusula `ONLY_SHORT`'a dönerse stop beklenmeden çıkılmalıdır.  
  * **Çözüm:** `if dir_bias == ONLY_SHORT and is_long:` durumunda pozisyon derhal piyasa emriyle kapatılmalıdır.
* **Dinamik ATR Çarpanının Stopu Gereksiz Genişletmesi (Soru 39):** Trend güçlüyken 3.0x ATR stop, tepe dönüşünde kârın %40'ının geri verilmesine yol açar.  
  * **Çözüm:** Trend olgunlaştıkça (kâr > 3R olduğunda) ATR çarpanı $1.8x$'e doğru sıkılaştırılmalıdır.
* **Gecelik Taşıma (Overnight) Marj Maliyetinin Çıkış Kararına Etkisi (Soru 40):** 3 gündür başabaşta gezinen pozisyon gecelik repo getirisini kaybettirir.  
  * **Çözüm:** Pozisyon 3 gündür $\pm 0.2R$ bandındaysa kapatılıp nakit ALE fonuna çekilmelidir.

---

### 🟢 5. Bölüm: Pozisyon Büyüklüğü, Portföy Dağılımı ve Fırsat Makinesi (Sorular 41 - 50)
* **%2 NAV Sabit Risk Bütçesinin Küçük Kasalarda 0 Lot Üretmesi (Soru 41):** 100.000 TL kasada %2 risk = 2.000 TL'dir. THYAO veya Endekste 2 ATR'lik risk 2.500 TL gerektiriyorsa sistem 0 lot hesaplayıp işlemi iptal eder.  
  * **Çözüm:** Küçük portföyler için "Asgari 1 Lot Güvencesi" eklenmeli; risk bütçesi portföyün $\%3.5$'ini aşmıyorsa en az 1 lot açılmasına izin verilmelidir.
* **Serbest Teminat (Margin Cap) Tıraşlamasının Orantısızlığı (Soru 42):** Serbest teminat 15.000 TL iken başlangıç teminatı 16.000 TL olan endekste işlem açılamaz.  
  * **Çözüm:** ALE fonundaki nakit anlık olarak teminata tahsis edilmelidir.
* **Maksimum Eşzamanlı Pozisyon Sınırı (Max Active Trades = 3) (Soru 43):** Rallide 6 hissede kırılım varken sadece ilk 3 hisse alınıp kalanlar reddedilir.  
  * **Çözüm:** Toplam risk bütçesi (%6 NAV) aşılmadığı sürece lotlar küçültülerek 5-6 pozisyona kadar dağıtılabilmelidir.
* **Sektörel Maruziyet Sınırı (%40) ve Rallilerde Kilitlenme (Soru 44):** Banka veya Havacılık rallisinde sektör payı %40'ı aşınca yeni işlem açılamaz.  
  * **Çözüm:** Sektörün göreceli gücü (RSC) endeksten güçlüyse sektörel limit $\%60$'a esnetilmelidir.
* **Piramitleme (Trend Yönünde Pozisyon Artırma) Yasağı (Soru 45):** Pozisyon 3R kâra geçtiğinde risk kalmamışken ilave lot eklenememektedir.  
  * **Çözüm:** Kâr $\ge 2.0R$ olduğunda ve yeni bir Donchian kırılımı geldiğinde "Bedava Piramitleme" ile $\%50$ ek lot açılmalıdır.
* **VİOP Kaldıraç Oranının Varlık Riskine Göre Dinamik Kullanılamaması (Soru 46):** Düşük betalı kamu bankası ile yüksek betalı hisse aynı muameleyi görür.  
  * **Çözüm:** Düşük betada risk bütçesi $\%2.5$, yüksek betada $\%1.5$ olarak kalibre edilmelidir.
* **Kasa Büyümesine Göre Lot Artışının (Compounding) Pasif Kalması (Soru 47):** Kâr çekişlerinde lotlar çok sert küçülmekte, toparlanma uzamaktadır.  
  * **Çözüm:** Keltner/Kelly kriteri tabanlı dinamik büyüme çarpanı kullanılmalıdır.
* **Nakit ALE Fonu Nemalanması ile Pozisyon Açma Arasında Fırsat Arbitrajı (Soru 48):** Gecelik repo %48 verirken zayıf teknik kırılıma girmek rasyonel değildir.  
  * **Çözüm:** Teknik motor sadece beklenen değeri gecelik repo getirisinin üzerinde olan sinyallere icra izni vermelidir.
* **Limit Emir Yerine Piyasa Emri ile Oluşan Kayma (Slippage) Maliyeti (Soru 49):** Piyasa emri 2-3 kademe kayma zararı yaratır.  
  * **Çözüm:** Kırılım anında `Limit Order at Best Ask` gönderilmeli, 10 saniyede dolmazsa pasife çekilmelidir.
* **Sistemin Sadece "Breakout" ile Sınırlandırılması ve "Mean-Reversion" Eksikliği (Soru 50):** Piyasa zamanının %70'ini yatay geçirirken sistemin sadece kırılım beklemesi yüzlerce günün boş geçmesine neden olmuştur.  
  * **Çözüm:** Yatay piyasalar için **"A-Tarzı Ortalamaya Dönüş (Mean-Reversion)"** motoru devreye alınmalıdır:
    * RSI < 30 ve Bollinger Alt Bandına iğne atan hisselerde orta banda (SMA20) kadar tepki alımı (0.75x bütçe),
    * RSI > 70 ve Bollinger Üst Bandında doji bırakan hisselerde orta banda kadar short satım.  
    Bu sayede sistem 365 gün hem trendden hem yatay piyasadan kesintisiz alfa üretecektir.
