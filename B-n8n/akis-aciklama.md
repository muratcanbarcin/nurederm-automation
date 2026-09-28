# Laptop Fiyat Takibi – n8n İş Akışı Mimari Dokümanı

| Başlık | Değer |
| --- | --- |
| İş akışı dosyası | `B-n8n/workflow.json` (n8n v1 dışa aktarım formatı, `executionOrder: v1`) |
| Hedef site | `https://webscraper.io/test-sites/e-commerce/static/computers/laptops?page=N` |
| Zamanlama | Her gün 09:00, cron `0 9 * * *`, saat dilimi `Europe/Istanbul` |
| Veri deposu | Google Sheets, yalnızca satır eklenen (append-only) `price_history` sayfası |
| Bildirim kanalı | Telegram (Markdown): fiyat değişiklikleri, kontrollü hatalar ve beklenmeyen hatalar |
| Node sayısı | 24 işlevsel node + 4 açıklama notu (sticky note) |

> Node adları, `workflow.json` içindeki adlarla birebir eşleşmesi için İngilizce bırakılmıştır.

## 1. Başlangıç Şablonu

**Kullanılan şablon:** [Competitor price monitoring with web scraping, Google Sheets & Telegram](https://n8n.io/workflows/4640-competitor-price-monitoring-with-web-scrapinggoogle-sheets-and-telegram/) (resmî n8n şablon kütüphanesi, şablon no. **#4640**, yazar: `tonydatahut`).

**Neden bu şablon seçildi?** Brief'te önerilen `https://n8n.io/workflows/1884-web-scraper-and-email-notification/` adresi **HTTP 404** döndürmektedir. 1884 numaralı şablon n8n'in herkese açık şablon API'sinde de (`api.n8n.io/api/templates/workflows/1884`) bulunmamaktadır. Var olmayan bir kaynağa atıf yapmamak için kütüphanede arama yapılmış ve istenen "web scraper + Telegram/E-posta bildirimi" desenine en yakın, gerçekten var olan şablon olarak #4640 seçilmiştir. Şablonun temel akışı şöyledir:

`Schedule Trigger -> Google Sheets (ürün listesi) -> Split In Batches -> Wait -> HTTP Request -> HTML Extract -> Code (fiyat normalizasyonu) -> Code (değişim hesabı) -> IF (değişti mi?) -> Google Sheets (geçmiş + ana tablo güncellemesi) -> Telegram`

Güncel n8n sürümleriyle uyumluluğu korumak için şablondaki node tipi sürümleri aynen kullanılmıştır: `scheduleTrigger 1.2`, `httpRequest 4.2`, `code 2`, `if 2.2`, `wait 1.1`, `googleSheets 4.5`, `telegram 1.2`.

## 2. Topoloji

```mermaid
flowchart LR
    T[Daily 09:00 Trigger] --> C[Workflow Config] --> I[Init Pagination State] --> P[Pagination State]
    P --> H[Fetch Laptop Page]
    H -- başarılı --> S{HTTP Status OK?}
    H -- hata çıkışı --> F[Build Failure Payload]
    S -- evet --> X[Parse & Normalize Page]
    S -- hayır --> F
    X --> Q{Page Healthy?}
    Q -- hayır --> F
    Q -- evet --> N{Has Next Page?}
    N -- evet --> A[Advance Page] --> D[Polite Delay] --> P
    N -- hayır --> Z[Finalize Snapshot] --> R[Read Price History] --> K[Detect Price Changes]
    K --> W[Append Snapshot to History]
    K --> O[Only Changed or New] --> B[Build Alert Message] --> M[Send Price Change Alert]
    F --> FA[Send Failure Alert] --> AB[Abort Execution]
    ET[On Unhandled Workflow Error] --> FU[Format Unhandled Error] --> CA[Send Critical Alert]
```

## 3. Veri Akışı ve Adımlar

Akış sırası: **Zamanlayıcı (09:00) → Sayfalama döngüsü → Veri çıkarma ve float fiyat dönüşümü → Zaman damgalı kayıt → Fark tespiti → Telegram bildirimi**. Bu hattın herhangi bir noktasında hata oluşursa akış **Hata Dalı**na yönlenir.

### 3.1 Zamanlayıcı ve merkezî yapılandırma

- **Daily 09:00 Trigger** (`scheduleTrigger`): `rule.interval[].field = cronExpression` ve `0 9 * * *` ifadesiyle her gün 09:00'da çalışır. İş akışı düzeyindeki `settings.timezone` değeri `Europe/Istanbul` olarak sabitlenmiştir. Böylece zamanlama, sunucunun saat diliminden bağımsız olarak İstanbul saatine göre işler.
- **Workflow Config** (`set`): Operatörün değiştirebileceği tüm parametreler tek bir yerde toplanmıştır:

  | Parametre | Varsayılan | Açıklama |
  | --- | --- | --- |
  | `maxPages` | 50 | Sonsuz döngüye karşı üst sayfa sınırı |
  | `requestDelaySeconds` | 1 | İki sayfa isteği arasındaki bekleme süresi |
  | `priceAnomalyThresholdPct` | 20 | Anomali sayılacak asgari yüzde değişim |
  | `telegramChatId` | — | Bildirimlerin gönderileceği sohbet |
  | `googleSheetId` | — | Geçmiş kayıtların tutulduğu tablo |
  | `historySheetName` | `price_history` | Tablodaki sayfa adı |

  Sonraki node'lar bu değerleri sabit olarak içermez; `$('Workflow Config').first().json` üzerinden okur.

### 3.2 Sayfalama döngüsü (`?page=N` ve `rel="next"` bitiş kontrolü)

- **Init Pagination State** (Code): Döngü durumunu oluşturur. Bu durum `page: 1`, `maxPages`, `pagesFetched: 0`, `runId` (= `$execution.id`), `runStartedAt` ve boş bir `products` biriktiricisinden oluşur.
- **Pagination State** (No-Op): Döngünün giriş noktasıdır. İlk durum da, her yeni sayfa için ilerletilmiş durum da bu node'dan geçer. Bu sayede Code node'ları, o anki turun durumunu her zaman `$('Pagination State').first()` ile okuyabilir.
- **Fetch Laptop Page** (HTTP Request): `...laptops?page={{ $json.page }}` adresine istek atar. Ayarları:
  - `fullResponse: true` ve `neverError: true`: 4xx/5xx yanıtları istisna fırlatmak yerine `statusCode` alanıyla veri olarak döner ve iş akışı içinde değerlendirilebilir.
  - `retryOnFail`: 3 deneme ve 3 saniye bekleme. Anlık ağ kesintilerini tolere eder.
  - `onError: continueErrorOutput`: Tekrar denemelere rağmen süren DNS, TLS ve zaman aşımı hataları ayrı bir ikinci çıkıştan hata dalına aktarılır.
  - Özel bir `User-Agent` başlığı ve 30 saniyelik zaman aşımı.
- **Has Next Page?** (IF): Döngünün bitiş koşuludur. Döngü yalnızca aşağıdaki **iki koşul birlikte** sağlandığında devam eder:
  1. Sayfanın HTML'inde `rel="next"` sayfalama bağlantısı bulunmalıdır. Canlı sitede son sayfa olan 20. sayfada "sonraki" düğmesi pasiftir ve `rel="next"` içermez.
  2. `page < maxPages` olmalıdır. Bu, site yapısı değişirse sonsuz döngüye girilmesini engelleyen kesin bir güvenlik sınırıdır.
- **Advance Page** (Code) sayfa numarasını bir artırır ve biriken ürünleri bir sonraki tura taşır. **Polite Delay** (Wait, 1 sn) siteyi yormamak için döngüyü *Pagination State*'e dönmeden önce yavaşlatır.

> **Bu tasarım neden gerekli?** Hedef site sayfalamanın bittiğini bir hata koduyla bildirmez: `?page=99` isteği **HTTP 200** döner, ancak sayfada hiç ürün yoktur. Yalnızca durum koduna bakan bir döngü düzgün şekilde sonlanamaz; ya güvenlik sınırına kadar boşuna döner ya da boş sayfaları veri olarak kaydeder.

### 3.3 Veri çıkarma ve `$` işaretinden arındırılmış sayısal (float) fiyat dönüşümü

**Parse & Normalize Page** (Code) her `.thumbnail` ürün kartını harici kütüphane gerektirmeyen düzenli ifadelerle (regex) ayrıştırır. Bu yöntem hem n8n Cloud'da hem de kendi sunucunuzdaki task runner'larda `NODE_FUNCTION_ALLOW_EXTERNAL` ayarına gerek kalmadan çalışır.

| Alan | Kaynak | Normalizasyon |
| --- | --- | --- |
| `title` | `a.title[title]` niteliği (link metni kısaltılmış olabileceği için tam ad buradan alınır) | HTML varlıkları çözülür, boşluklar sadeleştirilir |
| `price` | `[itemprop=price]` (yedek: `.price`) | `"$416.99"` → `0-9 . , -` dışındaki tüm karakterler silinir → binlik ayırıcılar kaldırılır → `parseFloat` → 2 ondalığa yuvarlanır → **`416.99` (Number)** |
| `review_count` | `[itemprop=reviewCount]` (yedek: `N reviews` metni) | `parseInt`, tam sayı |
| `rating` | `[data-rating]` | `parseInt` |
| `url` | `a.title[href]` (göreli adres) | Mutlak adrese çevrilir: `https://webscraper.io/test-sites/e-commerce/static/product/31` |
| `product_id` | `/product/{id}` içindeki sayısal kısım | Fark tespitinde kullanılan sabit anahtar |
| `description`, `currency`, `page` | Kart metni / sabit `USD` / döngü durumu | — |

Ürünler biriktiriciye `product_id` anahtarıyla eklenir; iki sayfada görünen bir ürün iki kez sayılmaz. Node, `status: "ok" | "error"` alanıyla sonuç döner. Hata durumları şunlardır:

- `ZERO_PRODUCTS`: Sayfalamaya göre var olması gereken bir sayfada ayrıştırılabilir ürün kartı bulunamadı (sayfa yapısı değişikliği, bot engeli veya boş sayfa).
- `PARSE_FAILURE`: En az bir kartta başlık, link ya da sayıya çevrilebilir bir fiyat eksik. Böyle bir kart hiçbir zaman sessizce atlanmaz.

### 3.4 Google Sheets'e zaman damgalı kayıt

- **Finalize Snapshot** (Code): Her ürüne `run_id` ve `scraped_at = $now.toISO()` değerlerini ekler. `scraped_at`, İstanbul saat farkını içeren ISO-8601 formatında bir zaman damgasıdır. Son bir güvenlik önlemi olarak, ürün listesi boşsa akışı durdurur.
- **Read Price History** (Google Sheets, `read`): Geçmiş kayıtları okur. `executeOnce` ve `alwaysOutputData` seçenekleriyle çalışır. Böylece ilk çalıştırmada tablo boş olsa bile tek bir boş kayıt üretilir ve akış kesilmez.
- **Append Snapshot to History** (Google Sheets, `append`, `autoMapInputData`): Tüm anlık görüntüyü ve fark bilgilerini tabloya ekler. Geçmiş yalnızca eklenerek büyür; her çalıştırmada her ürün için bir satır yazılır. Bu yapı, trend analizi için eksiksiz bir zaman serisi sağlar.

`price_history` sayfasında bulunması gereken başlık satırı (node içine gömülü sütun şemasıyla aynıdır):

```text
run_id | scraped_at | product_id | title | price | currency | review_count | rating | url | page | change_type | previous_price | price_delta | price_delta_pct | is_anomaly | is_baseline_run
```

> **Data Table alternatifi:** Yerleşik Data Tables özelliğine sahip n8n sürümlerinde aynı sütunlarla bir tablo oluşturulabilir. `price`, `previous_price`, `price_delta` ve `price_delta_pct` sütunları Number; `is_anomaly` ve `is_baseline_run` Boolean; diğerleri String olmalıdır. Ardından iki Google Sheets node'u *Data Table → Get rows* ve *Data Table → Insert row* ile değiştirilir. Başka hiçbir node'da değişiklik gerekmez.

### 3.5 Fark / değişiklik tespiti

**Detect Price Changes** (Code), geçmiş kayıtlardan `product_id → en son fiyat` eşlemesi çıkarır; her ürün için `scraped_at` değeri en yeni olan satırı esas alır. Kimliği olmayan veya fiyatı sayıya çevrilemeyen satırlar önlem olarak yok sayılır. Ardından güncel ürünlerin her biri sınıflandırılır:

| `change_type` | Kural |
| --- | --- |
| `NEW` | Ürün kimliği daha önce hiç görülmemiş |
| `PRICE_UP` / `PRICE_DOWN` | Fiyat, son kayıtlı değere göre en az $0.01 artmış / azalmış |
| `UNCHANGED` | Fiyat değişimi $0.01'den küçük |

Node ayrıca `previous_price`, `price_delta` ve `price_delta_pct` alanlarını hesaplar. Yüzde değişimin mutlak değeri `priceAnomalyThresholdPct` eşiğine ulaşırsa `is_anomaly` işaretlenir. Geçmiş tablo boşsa `is_baseline_run` değeri `true` olur.

### 3.6 Telegram bildirimi

- **Only Changed or New** (Filter): Yalnızca `change_type != UNCHANGED` **ve** `is_baseline_run == false` olan satırları geçirir. Böylece ilk çalıştırma sadece geçmişi oluşturur; ~117 ürünün tamamı için bildirim gönderilmez. Hiçbir değişiklik yoksa filtre çıktı üretmez ve mesaj gönderilmez.
- **Build Alert Message** (Code): Tüm değişiklikleri **tek bir** Telegram Markdown mesajında toplar. Mesaj şu bölümlerden oluşur: *ANOMALY* (değişim büyüklüğüne göre sıralı), *Price drops*, *Price increases*, *New listings*. Her bölüm en fazla 25 satır içerir ve mesaj Telegram'ın 4.000 karakter sınırına göre kırpılır. Ürün adları Markdown kaçışından geçirilir ve ürün sayfasına bağlanır.
- **Send Price Change Alert** (Telegram, `parse_mode: Markdown`, link önizlemesi kapalı).

Doğrulama çalıştırmasından örnek çıktı:

```text
*Laptop Price Monitor - Change Report*
Run: `sim-1001` | 2026-09-28T11:45:04.858Z
Scanned: 117 products across 20 pages | Changes: 3

*ANOMALY - price moved beyond threshold (2)*
- [Aspire E1-510](https://webscraper.io/test-sites/e-commerce/static/product/32): $406.99 -> *$306.99* (-24.57%)
...
*Price increases (1)*
- [ThinkPad T540p](https://webscraper.io/test-sites/e-commerce/static/product/33): $1177.99 -> *$1178.99* (+0.08%)
```

### 3.7 Hata Dalı (Stop and Error + Kritik Alarm)

| Hata türü | Tespit eden | Yönlendirme |
| --- | --- | --- |
| DNS / TLS / zaman aşımı / bağlantı kopması (3 denemeden sonra) | HTTP node'unun hata çıkışı (`continueErrorOutput`) | Build Failure Payload (`HTTP_TRANSPORT`) |
| HTTP 4xx / 5xx | **HTTP Status OK?** (`200 ≤ statusCode < 300`) | Build Failure Payload (`HTTP_STATUS`) |
| Erken gelen sıfır ürünlü sayfa veya fiyatı okunamayan kart | **Page Healthy?** (`status == ok`) | Build Failure Payload (`EXTRACTION`) |
| Diğer her şey (Sheets kota/yetki hatası, Telegram kesintisi, kod istisnası) | **On Unhandled Workflow Error** (Error Trigger) | Format Unhandled Error → Send Critical Alert |

**Kontrollü hata dalı** şu adımlarla işler:

1. **Build Failure Payload**: Hatanın oluştuğu aşamayı, sayfayı, URL'yi, o ana kadar tamamlanan sayfa sayısını, çalıştırma kimliğini ve hata ayrıntısını kaydeder.
2. **Send Failure Alert**: Telegram'a alarm gönderir. `onError: continueRegularOutput` ayarı sayesinde bildirim kanalı çalışmıyor olsa bile bir sonraki adım olan durdurma engellenmez.
3. **Abort Execution** (Stop and Error): Çalıştırmayı bilinçli olarak hatalı sonlandırır. Geçmiş tablosuna hiçbir şey yazılmaz. Böylece yarım kalmış ya da bozuk bir tarama, bir sonraki karşılaştırmanın referansı hâline gelemez. Çalıştırma n8n arayüzünde sessizce başarılı görünmek yerine *failed* olarak listelenir.

**Kritik Alarm (global güvenlik ağı):** Error Trigger, kontrollü dalın dışında kalan node'lardaki hataları yakalar. Etkinleştirmek için içe aktarılan iş akışında **Settings → Error Workflow → bu iş akışı** seçilmelidir. İş akışının kimliği ancak içe aktarıldıktan sonra oluştuğu için bu ayar JSON dosyasına eklenemez. *Format Unhandled Error*, *Abort Execution*'ın bilinçli olarak ürettiği hataları yok sayar; böylece her kontrollü hata için tek bir alarm gönderilir.

## 4. Şablona Göre Yapılan Mimari İyileştirmeler

### 4.1 Sayfalama mantığının eklenmesi

Baz şablon, bir tablodan okunan sabit bir ürün URL listesiyle çalışır ve her satır için tek bir HTTP isteği atar. Bu iş akışı ise **sayfalı bir kataloğu** dolaşır:

- Durumu tur boyunca taşıyan bir `?page=N` döngüsü kurulmuştur (*Pagination State* → … → *Polite Delay* → *Pagination State*).
- Bitiş kararı sayfa içeriğine bakılarak verilir: `rel="next"` bağlantısı yoksa döngü sonlanır.
- `maxPages` üst sınırı, sayfa yapısı değişse bile sonsuz döngüyü imkânsız kılar.
- Sayfalar arası ürünler `product_id` üzerinden tekilleştirilir.

### 4.2 `?page=99` boş sayfa senaryosunun defansif olarak yakalanması

Canlı testte `?page=99` isteğinin **HTTP 200** döndürdüğü ve sayfada **sıfır ürün** bulunduğu doğrulanmıştır. Baz şablonda böyle bir durum fark edilmez; boş bir seçici `NaN` fiyat olarak akışa girer. Bu iş akışında aynı senaryoya karşı katmanlı bir savunma vardır:

1. **Sayfa düzeyinde:** *Parse & Normalize Page*, ürün kartı bulamadığında `ZERO_PRODUCTS` durumu üretir. *Page Healthy?* bu durumu hata dalına yönlendirir.
2. **Döngü düzeyinde:** Döngü, `rel="next"` bağlantısı olmayan bir sayfanın ötesine hiç geçmez. Normal çalışmada 21. ve sonraki sayfalar zaten istenmez.
3. **Kayıt düzeyinde:** *Finalize Snapshot*, boş bir ürün listesini kaydetmeyi reddeder.

Bu senaryo otomatik testlerle de doğrulanmaktadır: 99. sayfa gerçekten `EXTRACTION` aşamasında hata dalına düşmektedir.

### 4.3 Hata yakalama mimarisi

Baz şablonda 4xx/5xx yanıtı veya zaman aşımı istisna fırlatır ve çalıştırma alarm gönderilmeden sonlanır. Bu iş akışında hatalar üç katmanda ele alınır:

- **Tolerans:** HTTP isteği 3 kez yeniden denenir.
- **Sınıflandırma:** Hatalar üç ayrı kapıdan geçer: taşıma hatası çıkışı, durum kodu kontrolü ve içerik sağlığı kontrolü.
- **Sonuç:** Önce alarm gönderilir, ardından *Stop and Error* ile çalıştırma durdurulur. Kalan tüm beklenmeyen hatalar Error Trigger üzerinden kritik alarm olarak bildirilir.

### 4.4 Karşılaştırmalı özet

| Alan | Baz şablon (#4640) | Bu iş akışı |
| --- | --- | --- |
| Girdi keşfi | Tablodan okunan sabit URL listesi | `?page=N` döngüsü, `rel="next"` bitiş kontrolü, `maxPages` sınırı, `product_id` ile tekilleştirme |
| Fiyat ayrıştırma | Doğrulama olmadan `parseFloat(str.replace(/[^0-9.]+/g, ""))`; `NaN` akışa karışabilir | Para birimi ve binlik ayırıcı temizliği, 2 ondalık yuvarlama, başarısızlıkta `null`. Okunamayan kart `NaN` kaydetmek yerine tüm sayfayı `PARSE_FAILURE` ile hatalı sayar |
| HTTP hataları | Varsayılan davranış; alarm yok | Yeniden deneme, `neverError` + durum kodu kapısı, taşıma hatası çıkışı, Telegram alarmı, bilinçli durdurma |
| Boş sonuçlar | Tespit edilmez | Sayfa başına `ZERO_PRODUCTS` kontrolü ve kayıt öncesi boş liste koruması |
| Geçmiş modeli | Ana tabloda `last_price` üzerine yazılır, geçmiş ayrıca tutulur | Tek bir append-only zaman serisi; önceki fiyat, ürünün en son satırından alınır (tek doğruluk kaynağı) |
| Değişim anlamı | `price_changed` boolean değeri | `NEW` / `PRICE_UP` / `PRICE_DOWN` / `UNCHANGED`, fark, yüzde ve `is_anomaly` eşiği |
| Bildirimler | Değişen her ürün için ayrı mesaj | Çalıştırma başına tek, gruplu ve Markdown kaçışlı özet; ilk çalıştırmada bildirim gönderilmez |
| Yapılandırma | Chat ID ve tablo kimlikleri birden çok node'a gömülü | **Workflow Config** node'unda merkezî |
| Gözlemlenebilirlik | Yok | Mükerrer alarm üretmeyen global Error Trigger dalı; tüm mesajlarda `runId` |

## 5. Kurulum

1. n8n'de **Workflows → Import from File** menüsünden `B-n8n/workflow.json` dosyasını içe aktarın.
2. **Workflow Config** node'unda `telegramChatId` ve `googleSheetId` değerlerini girin. `googleSheetId`, tablo URL'sindeki kimlik bölümüdür.
3. §3.4'teki başlık satırıyla `price_history` sayfasını oluşturun.
4. Kimlik bilgilerini bağlayın:
   - **Read Price History** ve **Append Snapshot to History** node'larına *Google Sheets OAuth2*;
   - üç Telegram node'una *Telegram Bot API*.

   **Send Critical Alert** node'undaki chat ID değerini de elle değiştirin; Error Trigger ayrı bir çalıştırmada tetiklendiği için *Workflow Config*'e erişemez.
5. **Settings → Error Workflow** ayarını bu iş akışının kendisi olarak seçin ve iş akışını etkinleştirin.

## 6. Doğrulama

`workflow.json` elle yazılmaz; incelenebilir kaynak dosyalardan üretilir ve otomatik olarak doğrulanır:

```powershell
.\.venv\Scripts\python.exe B-n8n\build_workflow.py      # B-n8n/code/*.js dosyalarını workflow.json içine gömer
.\.venv\Scripts\python.exe B-n8n\validate_workflow.py   # --offline: Node.js ve canlı site kontrollerini atlar
```

`validate_workflow.py` toplam 48 kontrol çalıştırır:

- **JSON ve graf bütünlüğü:** node adları ve kimlikleri benzersiz, kopuk bağlantı yok, her node bir tetikleyiciden erişilebilir.
- **Zorunlu node'lar:** gerekli tüm node tiplerinin varlığı.
- **Yapılandırma:** cron ifadesi, saat dilimi, sayfalı URL, döngü, bitiş koşulu, float dönüşümü, yeniden deneme ve hata çıkışı ayarları, hata yönlendirmesi, kayıt şeması, `$now` zaman damgası.
- **Code node'ları:** her Code node için `node --check` sözdizimi kontrolü.
- **Canlı simülasyon:** `tests/simulate_pipeline.js`, `workflow.json` içine gömülü JavaScript'i canlı siteye karşı çalıştırır ve şunları doğrular:
  - 20 sayfanın ve 117 ürünün tamamı alınır;
  - `"$416.99"` değeri Number tipinde `416.99` olur;
  - URL'ler mutlaktır;
  - bozuk geçmiş satırları dahil fark sınıflandırması doğrudur;
  - bildirim mesajı Telegram'ın uzunluk sınırını aşmaz;
  - 99. sayfanın sıfır ürün senaryosu `EXTRACTION` aşamasında hata dalına düşer;
  - mükerrer alarmlar engellenir.

## 7. Üretim Ortamı (Production) Yol Haritası

### 7.1 Proxy rotasyonu ve bot korumaları

Gerçek e-ticaret sitelerinde tek bir IP adresinden düzenli istek atmak kısa sürede engellenmeye yol açar. Önerilenler:

- HTTP isteğini dönüşümlü (rotating) residential veya datacenter proxy havuzu üzerinden geçirmek (HTTP Request → *Proxy* seçeneği).
- Alternatif olarak Bright Data, ScrapingBee veya Decodo gibi bir scraping API kullanmak.
- `User-Agent` başlıklarını dönüşümlü kullanmak.
- CAPTCHA veya ara sayfaları (interstitial) `ZERO_PRODUCTS` hatası olarak ele almak. Mevcut iş akışı bunu zaten yapmaktadır; bot engeli sessiz bir veri kaybına değil, alarma dönüşür.

### 7.2 IP bazlı hız sınırlama (rate limiting)

- Gerçek perakendeciler için `requestDelaySeconds` değerini artırmak ve isteklere rastgele sapma (jitter) eklemek.
- `robots.txt` kurallarına uymak.
- HTTP 429/503 yanıtlarında `Retry-After` başlığını dikkate almak. Örneğin 429 yanıtını ayrı bir IF node'uyla daha uzun bir Wait adımına yönlendirip ardından yeniden denemek.
- Birden fazla hedef site izleniyorsa zamanlamaları farklı saatlere dağıtmak ve alan adı başına eşzamanlı istek sayısını sınırlamak.

### 7.3 Headless browser (Puppeteer) ihtiyacı

Mevcut hedef sunucu tarafında oluşturulan (server-rendered) HTML sunar; bu nedenle düz HTTP isteği yeterlidir. İçeriği JavaScript ile yüklenen SPA kataloglarında ise (aynı test sitesinin `/ajax/` ve `/scroll/` varyantları gibi) ham HTML ürün içermez. Bu durumda:

- HTTP node'u bir headless browser katmanıyla değiştirilmelidir: Browserless/Puppeteer topluluk node'u, Playwright mikroservisi veya Firecrawl.
- Mümkünse sitenin arka planda çağırdığı JSON XHR uç noktası doğrudan kullanılmalıdır. Bu, tarayıcı çalıştırmaktan çok daha hızlı ve ucuzdur.

*Pagination State*'ten sonraki tüm katmanlar (ayrıştırma, kayıt, fark tespiti, bildirim ve hata dalı) değişmeden kalabilir.

### 7.4 Diğer üretim konuları

- **Seçici kayması (selector drift):** Seçicileri *Workflow Config*'e taşımak veya HTML node'unun CSS çıkarımını kullanmak önerilir. `PARSE_FAILURE` / `ZERO_PRODUCTS` korumaları korunmalıdır; sayfa yapısı değiştiğinde boş veri üretilmez, alarm gönderilir.
- **Depolama ölçeği:** Google Sheets birkaç yüz bin hücreden sonra yavaşlar. Geçmiş verisi `(product_id, scraped_at)` indeksli Postgres, BigQuery veya n8n Data Tables'a taşınmalı; tüm geçmişi okumak yerine yalnızca ürün başına en son satır sorgulanmalıdır.
- **Kaldırılan ürünler:** Son anlık görüntüde olup mevcut taramada bulunmayan ürünler `REMOVED` olarak raporlanabilir. Bu satırların eklenecek güncel fiyatı olmadığı için ayrı bir dal gerekir.
- **Eşzamanlılık ve idempotency:** Tek bir aktif zamanlama tutulmalı veya tarih bazlı bir kilit satırı kullanılmalıdır. Böylece manuel ve zamanlanmış çalıştırmalar çakışıp aynı günü iki kez kaydedemez.
- **Gizli bilgiler ve çok kanallı bildirim:** Chat ID ve tablo kimlikleri, lisans planı izin veriyorsa n8n Variables veya ortam değişkenlerinde tutulmalıdır. Yedeklilik için aynı `text` yükü Telegram'a paralel olarak E-posta veya Slack node'larına da gönderilebilir.
