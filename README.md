# Nurederm Otomasyon Projesi

Nurederm için hazırlanan bu depo iki bağımsız otomasyon çözümü içerir:

- **Bölüm A – Müşteri Mesajı Otomasyonu:** WhatsApp ve Instagram'dan gelen müşteri mesajlarını sınıflandıran, güvenlik ve tıbbi uyum kurallarını uygulayan, yanıt taslakları üreten ve yöneticilere Türkçe bir özet panosu sunan Python entegrasyonu.
- **Bölüm B – n8n Fiyat Takip Akışı:** Sayfalı bir e-ticaret kataloğunu her gün tarayan, fiyatları sayısal değere dönüştürüp zaman damgasıyla kaydeden, fiyat değişikliklerini tespit edip Telegram'dan bildiren ve hatalara karşı savunmalı bir n8n iş akışı.

| Başlık | Değer |
| --- | --- |
| Başlangıç | 28 Eylül 2026, 14:00 |
| Bitiş | 28 Eylül 2026, 16:45 |
| Toplam süre | ~2 saat 45 dakika |
| Dil / çalışma ortamı | Python 3.11+ (geliştirmede 3.13), Node.js 18+ (yalnızca doğrulama için), n8n v1 |
| Doğrulama durumu | `validate_talepler.py` 15/15 kayıt · `validate_workflow.py` 48/48 kural |

---

## 1. Proje Mimarisi

```text
nurederm-automation/
├── README.md                        # Bu doküman
├── requirements.txt                 # Python bağımlılıkları (pydantic, requests, urllib3)
├── .cursorrules                     # AI oturumları için kalıcı mühendislik ve güvenlik kuralları
├── .gitignore                       # Bytecode, sanal ortam, gizli bilgi ve IDE dışlamaları
├── A-mesaj-otomasyonu/
│   ├── mesajlar.json                # Girdi: 15 müşteri mesajı
│   ├── process_messages.py          # Sınıflandırma, IDOR kontrolü, ürün araması, taslak üretimi
│   ├── talepler.json                # Çıktı: katı şemalı talep kayıtları
│   ├── talepler.csv                 # Çıktı: Excel uyumlu (UTF-8 BOM) CSV dışa aktarımı
│   ├── generate_summary_html.py     # talepler.json -> ozet.html dönüştürücüsü
│   ├── ozet.html                    # Türkçe yönetici panosu (Tailwind CDN)
│   └── validate_talepler.py         # Şema ve iş kuralı doğrulayıcısı + yönetici özeti
├── B-n8n/
│   ├── workflow.json                # İçe aktarılabilir n8n v1 iş akışı
│   ├── akis-aciklama.md             # Türkçe mimari doküman
│   ├── build_workflow.py            # code/*.js dosyalarını workflow.json'a gömen üretici
│   ├── validate_workflow.py         # 48 kurallık yapısal ve davranışsal doğrulayıcı
│   ├── code/                        # Code node'larının JavaScript kaynakları (8 dosya)
│   └── tests/
│       └── simulate_pipeline.js     # Gömülü kodu canlı siteye karşı çalıştıran simülasyon
└── promptlar/
    ├── A-claude-code.md             # Bölüm A prompt denetim kaydı ve metodoloji
    └── B-n8n.md                     # Bölüm B prompt denetim kaydı ve metodoloji
```

---

## 2. Bölüm A – Müşteri Mesajı Otomasyonu

### 2.1 Kurulum ve çalıştırma

Aşağıdaki komutlar depo kök dizininden PowerShell ile çalıştırılır:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe A-mesaj-otomasyonu/process_messages.py        # talepler.json üretir
.\.venv\Scripts\python.exe A-mesaj-otomasyonu/generate_summary_html.py   # ozet.html üretir
.\.venv\Scripts\python.exe A-mesaj-otomasyonu/validate_talepler.py       # doğrular ve özetler
```

Script'ler dosya yollarını kendi konumlarına göre çözümler; hangi dizinden çalıştırıldıklarından bağımsız olarak doğru dosyaları okur ve yazar. DummyJSON istekleri 10 saniyelik zaman aşımıyla yapılır. 429/5xx yanıtlarında üç kez, artan bekleme süreleriyle (exponential backoff) yeniden denenir.

### 2.2 Sınıflandırma ve çıktı şeması

Her mesaj şu kategorilerden birine atanır: `urun-sorusu`, `fiyat`, `siparis-durumu`, `iade-sikayet`, `istenmeyen-etki`, `diger`.

Bir mesajda birden fazla niyet varsa kategori iş önceliğine göre seçilir: istenmeyen etki > iade/şikâyet > sipariş > fiyat > ürün. Birincil olmayan niyet yanıt taslağına ek bir cümleyle yansıtılır. Örneğin mesaj #8 hem sipariş durumu hem de güneş kremi fiyatı sorar.

Diğer davranışlar:

- **Dil tespiti:** İngilizce yazan müşteriye (mesaj #6) İngilizce yanıt taslağı üretilir.
- **Spam:** Şüpheli link veya takipçi satışı içeren mesajlar (mesaj #7) için "yanıt gönderilmemelidir" taslağı üretilir.

`talepler.json` her kayıt için tam olarak şu alanları içerir: `id`, `konu`, `oncelik`, `devret`, `cevap_taslagi`, `not`.

**Operasyonel öncelik (`oncelik`):** Her kayda deterministik bir öncelik atanır. Kategori bir taban değer belirler; sipariş sorgusunun sonucu bu değeri yalnızca yükseltebilir.

| Öncelik | Koşul | Örnek |
| --- | --- | --- |
| `YUKSEK` | `istenmeyen-etki` (hasta güvenliği) veya IDOR / müşteri uyuşmazlığı | #1, #4 |
| `ORTA` | `iade-sikayet`, bulunamayan (HTTP 404) veya API hatası nedeniyle doğrulanamayan sipariş | #3, #5 |
| `DUSUK` | Rutin talepler: `urun-sorusu`, `fiyat`, `diger`, sahipliği doğrulanmış sipariş, sipariş numarası içermeyen sipariş sorusu | Diğerleri |

**CSV dışa aktarımı:** Aynı kayıtlar `mesajlar.json` ile birleştirilerek `talepler.csv` dosyasına yazılır. Sütunlar: `id`, `kanal`, `musteri_id`, `konu`, `oncelik`, `devret`, `cevap_taslagi`, `not`. Dosya UTF-8 BOM ile kodlanır; böylece Excel Türkçe karakterleri doğru gösterir. `validate_talepler.py`, CSV'nin BOM'unu, başlığını ve `talepler.json` ile satır satır tutarlılığını da doğrular. `oncelik` alanı içermeyen eski `talepler.json` dosyaları geriye dönük uyumluluk için hâlâ geçerli kabul edilir.

### 2.3 Güvenlik ve IDOR koruması

Sipariş sorularında mesajdan sipariş numarası ayrıştırılır ve `GET https://dummyjson.com/carts/{id}` ile sepet sorgulanır. Sepet içeriği **yalnızca** `cart.userId == musteri_id` olduğunda paylaşılır.

**Mesaj #1 – engellenen IDOR girişimi:** `musteri_id=7` olan müşteri 12 numaralı siparişi sormuştur. DummyJSON'a göre bu sepet **`userId=12`** kullanıcısına aittir. Sistem bu durumda:

- tutarsızlığı yetkisiz erişim girişimi olarak işaretler;
- sepetteki ürünleri ve tutarı **gizler**;
- müşteriye kimlik doğrulaması gerektiğini bildiren nötr bir yanıt üretir;
- kaydı `devret: true` ile insana devreder;
- `not` alanına `SECURITY:` önekli bir güvenlik uyarısı yazar.

> Brief'te bu kayıt için "sepet_userId=2" değeri geçmektedir. Canlı API yanıtı ve üretilen `talepler.json` ise sepet sahibinin `userId=12` olduğunu göstermektedir. Bu dokümanda doğrulanmış değer kullanılmıştır. Güvenlik kararı her iki değerde de aynıdır, çünkü müşteri 7 sepetin sahibi değildir.

Diğer sipariş senaryoları:

| Senaryo | Davranış |
| --- | --- |
| Sahiplik doğrulandı (#2, #6, #8) | Ürün listesi ve toplam tutar paylaşılır |
| Sipariş bulunamadı, HTTP 404 (#3, 9999 numaralı sipariş) | Müşteriden numarayı kontrol etmesi kibarca istenir; devir yok |
| API hatası veya beklenmeyen yanıt | Sipariş bilgisi paylaşılmaz, manuel kontrol için insana devredilir |

### 2.4 Tıbbi ve hukuki güvenlik

`istenmeyen-etki` (ör. #4: "yüzüm yandı ve kızardı") ve `iade-sikayet` (ör. #5: "kutu ezik geldi") kategorilerinde kod düzeyinde **her koşulda `devret: true`** uygulanır. Yanıt taslağı yalnızca empati ve devir bilgisi içerir:

- teşhis konulmaz;
- tedavi veya kullanım tavsiyesi verilmez;
- ürün önerilmez;
- katalog araması bu kategorilerde hiç çalıştırılmaz.

Talep, uzman müşteri temsilcisine yönlendirilir.

### 2.5 Bonus: Ürün arama entegrasyonu (`/products/search`)

`urun-sorusu` ve `fiyat` kategorilerinde mesajdaki kozmetik terimler çıkarılır ve İngilizce katalog terimlerine çevrilir. Örneğin `güneş kremi` → `sunscreen`, `c vitamini` → `vitamin c`, `nemlendirici` → `moisturizer`, `krem` → `cream`. Ardından `GET https://dummyjson.com/products/search?q={terim}` ile arama yapılır.

**DummyJSON katalog kısıtları:** Katalogda gerçek bir kozmetik serisi bulunmamaktadır. `serum`, `retinol`, `vitamin c`, `toner` ve `sunscreen` aramaları sonuç döndürmez. Arama gevşek çalışır; örneğin `cream` araması **"Ice Cream"** (market ürünü) ve açıklamasında "creamy" geçen bir rujla eşleşir. "İlk sonucu al" yaklaşımı, krem soran müşteriye dondurma fiyatı yazdırabilirdi. Bu nedenle üç hijyen filtresi uygulanır:

1. **Kategori filtresi:** Yalnızca `beauty` ve `skin-care` kategorilerindeki ürünler kabul edilir.
2. **Tam kelime eşleşmesi:** Terim, ürün başlığında (öncelikli) veya açıklamasında tam kelime olarak geçmelidir. "creamy" kelimesi `cream` sayılmaz.
3. **Özgüllük kuralı:** Mesajda özel bir terim (retinol, C vitamini, güneş kremi, nemlendirici) varsa genel bir terime (serum, krem) geri düşülmez. Retinol serumu soran müşteriye alakasız bir serum sunulmaz.

Eşleşme bulunursa ürün adı ve güncel fiyatı yanıt taslağına eklenir. Mesaj #10'da "Nemlendirici krem ne kadar?" sorusu "Olay Ultra Moisture Shea Butter Body Wash — $12.99" ile eşleşmiştir. Eşleşme yoksa veya API hata verirse kibar standart yanıt korunur. Her iki durumda da aranan terim ve sonuç, temsilcinin kontrolü için `not` alanına yazılır.

### 2.6 `ozet.html` yönetici panosu

`generate_summary_html.py` tarafından `talepler.json` ve `mesajlar.json` verilerinden üretilen, tek sayfalık, Tailwind CDN tabanlı Türkçe panodur. İçeriği:

- **Metrik kartları:** İşlenen Toplam Mesaj, İnsana Devredilen Talepler ("Aksiyon Gerekli" rozeti ve yüzde oranı), Yüksek Öncelikli Vakalar (sayı ve vaka listesi), Güvenlik İhlali / Engellenen IDOR (ihlal ayrıntısıyla birlikte).
- **Kategori dağılımı:** Altı kategori için dinamik sayaç kartları.
- **Filtreler:** "Tümü", "İnsana Devredilenler", "Doğrudan Yanıtlananlar". Filtreye uyan kayıt yoksa boş durum mesajı gösterilir.
- **CSV Olarak İndir:** O anda görünen (filtrelenmiş) satırları, `talepler.csv` ile aynı sütun yapısında ve UTF-8 BOM ile tamamen tarayıcı tarafında indirir. Dosya adı aktif filtreyi yansıtır (ör. `talepler-insana-devredilenler.csv`).
- **Talep tablosu:** Kanal, kategori ve renk kodlu öncelik rozetleri (kırmızı YÜKSEK, amber ORTA, yeşil DÜŞÜK), devir durumu, yanıt taslağı ve dahili not. İngilizce güvenlik notları panoda Türkçe gösterilir; IDOR kaydı "Güvenlik İhlali" rozetiyle öne çıkarılır.

Tüm sayılar veriden hesaplanır; panoda sabit değer bulunmaz. Kullanıcı kaynaklı metinler HTML kaçışından geçirilir.

---

## 3. Bölüm B – n8n Fiyat Takip Akışı

Ayrıntılı mimari için bkz. [`B-n8n/akis-aciklama.md`](B-n8n/akis-aciklama.md).

### 3.1 Başlangıç şablonu

Akış, resmî n8n kütüphanesindeki [**#4640 – Competitor price monitoring with web scraping, Google Sheets & Telegram**](https://n8n.io/workflows/4640-competitor-price-monitoring-with-web-scrapinggoogle-sheets-and-telegram/) şablonu temel alınarak geliştirilmiştir.

Brief'te önerilen `n8n.io/workflows/1884-web-scraper-and-email-notification/` adresi **HTTP 404** döndürmektedir; 1884 numaralı şablon n8n şablon API'sinde de bulunmamaktadır. Var olmayan bir kaynağa atıf yapmak yerine, istenen "web scraper + bildirim" desenine en yakın gerçek şablon seçilmiştir. Şablonun node tipi sürümleri korunmuştur.

### 3.2 Sayfalama döngüsü ve `?page=99` savunması

Hedef: `https://webscraper.io/test-sites/e-commerce/static/computers/laptops?page=N`.

- Döngü `page=1` ile başlar ve her turda `?page={{ $json.page }}` adresini çeker.
- Döngü yalnızca sayfada `rel="next"` bağlantısı varsa **ve** `page < maxPages` (50) ise devam eder. Canlı sitede 20. sayfada `rel="next"` bulunmadığı için döngü 20 sayfada sonlanır ve 117 benzersiz ürün toplanır.
- **Boş sayfa açığı:** Site, olmayan sayfalar için hata dönmez. `?page=99` **HTTP 200** döner, ancak sıfır ürün içerir. Yalnızca durum koduna bakan bir döngü bu durumu fark edemez. Bu nedenle üç katmanlı bir savunma uygulanır:
  1. Sayfa düzeyinde `ZERO_PRODUCTS` kontrolü;
  2. döngü düzeyinde `rel="next"` bitiş koşulu;
  3. kayıt öncesinde boş liste koruması.

  Bu senaryo otomatik testle doğrulanmıştır.
- Her istek arasında 1 saniyelik nezaket beklemesi (Polite Delay) vardır.

### 3.3 Veri dönüşümü, kayıt, fark tespiti ve bildirim

| Aşama | Uygulama |
| --- | --- |
| Zamanlama | Her gün 09:00, cron `0 9 * * *`, saat dilimi `Europe/Istanbul` |
| Veri çıkarma | Başlık, yorum sayısı (tam sayı), mutlak ürün linki, puan, ürün kimliği |
| Float fiyat dönüşümü | `"$416.99"` → para birimi ve binlik ayırıcılar temizlenir → `parseFloat` → **`416.99` (Number)**. Okunamayan fiyat sessizce atlanmaz; sayfa `PARSE_FAILURE` ile hatalı sayılır |
| Zaman damgası | Her ürüne `$now.toISO()` ile ISO-8601 `scraped_at` ve `run_id` eklenir |
| Kayıt | Google Sheets `price_history` sayfasına yalnızca satır eklenir (append-only), 16 sütunlu şema kullanılır |
| Fark tespiti | Ürün başına son kayıtlı fiyatla karşılaştırma: `NEW` / `PRICE_UP` / `PRICE_DOWN` / `UNCHANGED`; ≥ %20 değişim `is_anomaly` olarak işaretlenir |
| Bildirim | Değişiklikler tek, gruplu bir Telegram Markdown mesajında gönderilir. İlk çalıştırmada yalnızca geçmiş oluşturulur, bildirim gönderilmez |

### 3.4 Hata dalı (Stop and Error + Kritik Alarm)

- **Kontrollü dal:** Aşağıdaki durumların tamamı *Build Failure Payload* node'unda toplanır:
  - 3 denemeden sonra da süren HTTP taşıma hataları;
  - 4xx/5xx yanıtları;
  - sıfır ürünlü veya okunamayan sayfalar.

  Ardından Telegram'dan hata alarmı gönderilir ve **Stop and Error** ile çalıştırma bilinçli olarak durdurulur. Tabloya hiçbir şey yazılmaz; yarım kalmış bir tarama bir sonraki karşılaştırmanın referansı olamaz.
- **Kritik Alarm:** Global **Error Trigger** dalı, kontrollü dalın dışında kalan hataları yakalar (Sheets kotası, Telegram kesintisi, kod istisnası). Kontrollü dalın ürettiği hatalar bu dalda yok sayılır, böylece aynı hata için iki kez alarm gönderilmez.

### 3.5 İçe aktarma

1. n8n'de **Workflows → Import from File** menüsünden `B-n8n/workflow.json` dosyasını seçin.
2. **Workflow Config** node'unda `telegramChatId` ve `googleSheetId` değerlerini girin.
3. Google Sheets ve Telegram kimlik bilgilerini bağlayın. **Send Critical Alert** node'undaki chat ID değerini de elle değiştirin.
4. **Settings → Error Workflow** ayarını bu iş akışının kendisi olarak seçin ve iş akışını etkinleştirin.

---

## 4. Test ve Doğrulama Metodolojisi

### 4.1 Otomatik doğrulama

```powershell
.\.venv\Scripts\python.exe A-mesaj-otomasyonu/validate_talepler.py   # Bölüm A: 15/15 kayıt
.\.venv\Scripts\python.exe B-n8n/validate_workflow.py                # Bölüm B: 48/48 kural (--offline: canlı testleri atlar)
```

**`validate_talepler.py` (15/15 kayıt):**

- Kök elemanın bir dizi olması ve tam olarak 15 kayıt içermesi.
- Her kayıtta tam olarak beş zorunlu alanın bulunması; tiplerin doğruluğu.
- Kimliklerin benzersiz olması ve girdiyle birebir eşleşmesi; kategorilerin geçerliliği.
- `istenmeyen-etki` ve `iade-sikayet` kayıtlarında zorunlu `devret: true`.
- `SECURITY:` notlu kayıtların insana devredilmiş olması.
- Doğrulamanın ardından kategori dağılımı, devirler ve güvenlik ihlallerini içeren bir yönetici özeti yazdırılır.

**`validate_workflow.py` (48/48 kural):**

- JSON ayrıştırılabilirliği ve graf bütünlüğü: benzersiz adlar ve kimlikler, kopuk bağlantı olmaması, her node'un bir tetikleyiciden erişilebilir olması.
- Zorunlu node'lar: Schedule Trigger, HTTP Request, Code, IF, Google Sheets, Filter, Telegram, Stop and Error, Error Trigger.
- Yapılandırma: cron ifadesi, saat dilimi, sayfalı URL, döngü ve bitiş koşulu, float dönüşümü, yeniden deneme ve hata çıkışı ayarları, zaman damgası, kayıt şeması.
- Tüm Code node'ları için `node --check` sözdizimi kontrolü.
- Canlı uçtan uca simülasyon: 20 sayfa / 117 ürün, `416.99` float değeri, fark sınıflandırması, `?page=99` hata dalı, mükerrer alarm engeli.

### 4.2 Manuel kontroller ve UI doğrulama adımları

1. **Regresyon karşılaştırması:** Bonus entegrasyonundan önceki ve sonraki `talepler.json` dosyaları alan alan karşılaştırılmıştır. Kategoriler, `devret` alanları ve IDOR kaydı değişmemiştir; yalnızca beklenen zenginleştirme ve not alanları güncellenmiştir.
2. **Uç durum testleri:** Sahte arama fonksiyonuyla şunlar doğrulanmıştır:
   - API 503 hatasında standart yanıt;
   - boş sonuç;
   - "Ice Cream" ve "creamy" eleme;
   - özgüllük kuralı;
   - İngilizce mesaj;
   - istenmeyen etki mesajında ürün adının yazılmaması.
3. **UI doğrulaması (`ozet.html`):**
   - Dosyayı tarayıcıda açın. Metrik kartlarında 15 toplam mesaj, 3 devir ve 1 güvenlik ihlali görünmelidir.
   - "İnsana Devredilenler" filtresine tıklayın; yalnızca #1, #4 ve #5 listelenmelidir.
   - "Doğrudan Yanıtlananlar" filtresinde kalan 12 kayıt görünmelidir; "Tümü" tüm kayıtları geri getirmelidir.
   - #1 satırında "Güvenlik İhlali" rozetinin ve Türkçe güvenlik notunun göründüğünü, sepet içeriğinin ise hiçbir yerde yer almadığını doğrulayın.
4. **n8n içe aktarma kontrolü:** `workflow.json` dosyasını n8n'e aktarın, kimlik bilgilerini bağlayın ve **Execute Workflow** ile manuel çalıştırın. İlk çalıştırmada tabloya 117 satır eklenmeli ve fiyat bildirimi gönderilmemelidir (baseline).

### 4.3 AI orkestrasyon kayıtları

Yapay zekâ destekli geliştirme sürecinin metodolojisi, faz bazlı kararları ve ham prompt kayıtları [`promptlar/A-claude-code.md`](promptlar/A-claude-code.md) ve [`promptlar/B-n8n.md`](promptlar/B-n8n.md) dosyalarında belgelenmiştir.
