# Bölüm B – n8n Fiyat Takip Akışı: Prompt Denetim Kaydı


## Mühendislik ve AI Orkestrasyon Metodolojisi

Bu kayıt, Bölüm B teslimatının (n8n iş akışı ve mimari dokümanı) yapay zekâ destekli olarak nasıl tasarlandığını, üretildiğini ve doğrulandığını belgelemektedir. Çalışma boyunca üç temel ilke uygulanmıştır:

1. **AI-assisted engineering:** 3 saatlik kısıtlı süre zarfında kurumsal ve hatasız bir mimari teslim edebilmek için yapay zekâ, bir mimari planlama ve hızlandırma aracı olarak kullanılmıştır. Topoloji, hata politikası ve kabul kriterleri mühendis tarafından belirlenmiş; yapay zekâ bu çerçeve içinde uygulama hızını artırmıştır.

### ÖNEMLİ NOT: PROMPTLAR ve ÇIKTILAR İLGİLİ KISIMLARIN "Doğrulama" kısmından sonra ayrı ayrı verilmiştir."

2. **Görev ayrıştırma (task decomposition) ve meta-prompting:** Kontrolsüz tek bir prompt yerine görevler modüler parçalara ayrılmıştır: şablon araştırması, akış topolojisi, JSON üretimi, doğrulama ve dokümantasyon. Her fazda şu kısıtlar açıkça verilmiştir:
   - n8n v1 şema uyumluluğu;
   - `?page=N` döngüsü;
   - `$` işaretinden arındırılmış float fiyat;
   - ISO zaman damgası;
   - açık bir hata dalı.
3. **Doğrula, sonra kabul et:** Üretilen hiçbir mantık doğrudan kabul edilmemiştir. Her çıktı şu yöntemlerle adım adım doğrulanmış ve gerektiğinde revize edilmiştir:
   - uç durum (edge case) senaryoları;
   - sahte geçmiş verileri;
   - hedef siteye ve n8n şablon API'sine yapılan canlı HTTP istekleri;
   - `validate_workflow.py` validasyon script'i.

### Kayıt formatı

Her faz aşağıdaki yapıyı izler:

- **Amaç:** Fazın iş hedefi.
- **Verilen kısıtlar:** Prompt'a eklenen teknik sınırlar.
- **Doğrulama:** Çıktının nasıl test edildiği.
- **Ham prompt ve çıktı:** Oturum kaydının orijinal (İngilizce) hâli.

---

## Faz 1: Hedef Site Keşfi ve Şablon Araştırması

**Amaç:** Hedef sitenin HTML ve sayfalama yapısını çözümlemek ve resmî n8n kütüphanesinden gerçek bir başlangıç şablonu belirlemek.

**Verilen kısıtlar:**

- Referans olarak resmî n8n kütüphanesinden bir "web scraper + bildirim" şablonu kullanılması.
- Seçicilerin varsayıma değil, canlı HTML'e dayanması.

**Doğrulama:**

- Canlı HTML incelemesi sonucunda şunlar belirlenmiştir:
  - ürün kartları `card thumbnail` bloklarında, fiyatlar `itemprop="price"` içinde bulunur;
  - toplam 20 sayfa vardır;
  - son sayfada `rel="next"` bağlantısı yoktur.
- `?page=99` isteğinin **HTTP 200** döndürdüğü, ancak sayfanın **sıfır ürün** içerdiği tespit edilmiştir. Bu nedenle bitiş koşulu durum koduna dayandırılmamıştır.
- n8n şablon API'si üzerinden aday şablonların node listeleri ve tip sürümleri karşılaştırılmıştır.

## Faz 2: Akış Topolojisi ve `workflow.json` Üretimi

**Amaç:** Günlük 09:00 zamanlayıcısı, sayfalama döngüsü, float fiyat dönüşümü, Google Sheets kaydı, fark tespiti, Telegram bildirimi ve hata dalını içeren, içe aktarılabilir bir n8n v1 iş akışı üretmek.

**Verilen kısıtlar:**

- Cron `0 9 * * *` ve `Europe/Istanbul` saat dilimi.
- `?page={{ $json.page }}` ile sayfalama; `rel="next"` bitiş kontrolü ve `maxPages: 50` güvenlik sınırı.
- `"$416.99"` → `416.99` (Number) dönüşümü; okunamayan fiyatların sessizce atlanmaması.
- HTTP taşıma hataları, 4xx/5xx yanıtları ve sıfır ürünlü sayfalar için alarm gönderip çalıştırmayı durduran (Stop and Error) açık bir hata dalı.

**Doğrulama:**

- Code node'larının JavaScript'i ayrı `.js` dosyalarında tutulmuş, `build_workflow.py` ile deterministik olarak `workflow.json`'a gömülmüştür.
- `validate_workflow.py` ile 48 kural doğrulanmıştır:
  - graf bütünlüğü;
  - zorunlu node'lar;
  - döngü ve bitiş koşulu;
  - hata yönlendirmesi;
  - `node --check` sözdizimi kontrolü.
- `tests/simulate_pipeline.js`, `workflow.json` içindeki gerçek kodu canlı siteye karşı çalıştırmıştır. Sonuçlar:
  - 20 sayfa ve 117 ürün alınmıştır;
  - `416.99` float değeri doğrulanmıştır;
  - sahte geçmiş verisiyle fiyat artışı, düşüşü ve anomali sınıflandırması doğru çalışmıştır;
  - `?page=99` senaryosu `EXTRACTION` aşamasında hata dalına düşmüştür.

*PROMPT:*
Act as a Senior Automation & Integration Architect. Let's execute Phase 3: Section B (n8n Workflow Design).

Objective:
Design a production-grade, standard-compliant n8n workflow for scraping e-commerce laptop listings, tracking price fluctuations, and alerting on anomalies.
Target Site: https://webscraper.io/test-sites/e-commerce/static/computers/laptops (paginated with ?page=N).

Deliverables:
1. `B-n8n/workflow.json`: A strictly valid, importable n8n v1 workflow JSON.
2. `B-n8n/akis-aciklama.md`: A comprehensive technical markdown document explaining the architecture.

Technical Architecture for workflow.json:
1. Base Template Reference:
   - Identify a reputable baseline template from the official library: "Web Scraper and Telegram/Email Notification" (e.g., https://n8n.io/workflows/1884-web-scraper-and-email-notification/).
2. Nodes & Workflow Topology:
   a. Schedule Trigger: Runs once daily at 09:00 AM (cron: '0 9 * * *').
   b. Pagination Loop (Loop Over Pages):
      - Initializes page counter starting at page 1.
      - HTTP Request Node: Fetches HTML from `https://webscraper.io/test-sites/e-commerce/static/computers/laptops?page={{ $json.page }}`.
      - Stop condition: Evaluates whether the returned page contains laptops or reaches pagination bounds, exiting gracefully when complete.
   c. Data Extraction & Normalization (Code / Function Node):
      - Extracts: Product title, review count (number), product link (absolute URL).
      - CRITICAL: Sanitizes price strings (e.g. "$416.99" -> 416.99 as a numeric Float, eliminating currency symbols).
   d. Error Branch & Resilience (Error Trigger / If Condition):
      - If HTTP response fails (4xx/5xx) or zero products are returned prematurely:
      - Routes to an "Alert Failure" node (Telegram/Email alert) and aborts execution to prevent silent failures.
   e. Data Persistence:
      - Appends data with an ISO timestamp (`{{ $now }}`) into n8n Data Table / Google Sheets schema format.
   f. Change Detection & Notification:
      - Compares current price against the previous snapshot.
      - Filters for items with changed prices or newly introduced products.
      - Sends a structured Markdown alert message via Telegram / Email / Slack summary node for detected changes.

Requirements for B-n8n/akis-aciklama.md:
- Written in clear, professional technical language.
- Specifies exact starting template (Name + Link) from n8n.io.
- Breaks down the step-by-step data pipeline (Trigger -> Pagination -> Extraction & Float sanitization -> Storage -> Diff detection -> Notifications).
- Explains architectural modifications made to the baseline template (especially multi-page handling, defensive error branching, and numeric price parsing).
- Outlines future production considerations (rate limiting/proxies, headless rendering for JS-rendered sites).

Execution:
1. Generate `B-n8n/workflow.json` with valid JSON syntax and authentic n8n v1 node schemas.
2. Generate `B-n8n/akis-aciklama.md`.
3. Validate that `workflow.json` is parseable and contains all mandatory nodes.

*OUTPUT:*
Section B tamamlandı. B-n8n/workflow.json geçerli bir JSON, zorunlu tüm node'ları içeriyor ve 48 doğrulama kontrolünün hepsini geçti. Bu kontrollere, Code node'larının canlı siteye karşı uçtan uca çalıştırılması da dahil. Dosyayı gerçek bir n8n kurulumuna içe aktarıp çalıştırmadım; node sürümlerini ve parametre yapısını resmi bir n8n şablonuyla karşılaştırarak doğruladım.

Şablon linkinde düzeltme: Brief'te verilen n8n.io/workflows/1884-... linki 404 dönüyor, n8n'in şablon API'sinde de 1884 numaralı bir şablon yok. Dokümana uydurma bir referans yazmak yerine kütüphanede bu işe en yakın gerçek şablonu kullandım: Competitor price monitoring with web scraping, Google Sheets & Telegram (#4640). Node sürümleri de bu şablonla aynı.

Siteyle ilgili kritik bulgu: Hedef site olmayan sayfalar için hata dönmüyor; ?page=99 HTTP 200 dönüyor ama içinde ürün yok. Bu yüzden döngü durum koduna göre değil, iki koşula göre duruyor:

Sayfada rel="next" bağlantısı yoksa (son sayfa olan 20'de yok) döngü biter.
Güvenlik sınırı olarak maxPages = 50 aşılmaz.
Workflow'un yapısı:

Tetikleme: Her gün 09:00'da çalışıyor (0 9 * * *, saat dilimi Europe/Istanbul).

Sayfalama: ?page={{ $json.page }} ile sayfa sayfa ilerliyor. Her sayfanın ürünleri biriktiriliyor, aynı ürün iki kez sayılmıyor ve istekler arasında 1 saniye bekleniyor.

Ayrıştırma: Her üründen başlık, yorum sayısı (tam sayı) ve mutlak ürün linki alınıyor. Fiyatlar sayıya çevriliyor: "$416.99" → 416.99. Fiyatı okunamayan bir ürün sessizce atlanmıyor, o sayfa hata sayılıyor.

Hata dalı: Üç durum aynı alarm akışına gidiyor:

3 denemeden sonra da süren bağlantı hatası;
4xx/5xx durum kodu;
ürünsüz ya da okunamayan sayfa.
Önce Telegram alarmı gidiyor, ardından Stop and Error ile çalışma bilerek hatalı bitiriliyor ve tabloya hiçbir şey yazılmıyor. Bu dalın dışında kalan hatalar için ayrıca bir Error Trigger var; aynı hata için iki kez alarm gitmiyor.

Kayıt ve fark tespiti: Her ürüne $now ile ISO zaman damgası ekleniyor ve Google Sheets'teki price_history sayfasına satır olarak ekleniyor (eski satırlar silinmiyor). Her ürün bir önceki kayıtla karşılaştırılıp NEW, PRICE_UP, PRICE_DOWN veya UNCHANGED olarak işaretleniyor. Fiyatı %20 veya daha fazla değişen ürün ayrıca anomali sayılıyor.

Bildirim: Değişiklikler tek bir gruplu Telegram Markdown mesajında gidiyor. İlk çalışmada yalnızca geçmiş oluşturuluyor; 117 ürünün hepsi için alarm gönderilmiyor.

Doğrulamada görülenler: 20 sayfanın tamamı gezildi ve 117 ürün alındı. Tüm fiyatlar sayı olarak geldi, linkler mutlak adres. Fiyat değişikliği sınıflandırması ve anomali eşiği doğru çalıştı; bozuk geçmiş satırları yok sayıldı. Sayfa 99 senaryosu doğru şekilde hata dalına gitti.

workflow.json elle yazılmadı. Code node'larının JavaScript'i B-n8n/code/ klasöründe ayrı dosyalarda duruyor; bunları build_workflow.py birleştiriyor, validate_workflow.py de kontrol ediyor. Yeniden üretmek ve doğrulamak için:

.\.venv\Scripts\python.exe B-n8n\build_workflow.py
.\.venv\Scripts\python.exe B-n8n\validate_workflow.py   # canlı site testini atlamak için: --offline
İçe aktardıktan sonra senin yapman gerekenler:

Workflow Config node'unda telegramChatId ve googleSheetId değerlerini gir.
Google Sheets ve Telegram kimlik bilgilerini bağla.
Send Critical Alert node'undaki chat ID'yi de elle değiştir; bu node ayrı bir çalışmada tetiklendiği için Workflow Config'i okuyamıyor.
Settings → Error Workflow ayarını bu workflow'un kendisi yap. Workflow'un kimliği ancak içe aktarıldıktan sonra oluştuğu için bu ayar JSON'a konamıyor.
akis-aciklama.md dokümanını İngilizce yazdım, çünkü .cursorrules Türkçeyi yalnızca ozet.html ve kök README.md için istiyor. Türkçe olmasını istersen çevirebilirim. Doküman şablon referansını, veri akışını adım adım, şablona göre yapılan değişiklikleri ve üretim için önerileri (rate limiting, proxy, headless tarayıcı) içeriyor. B-n8n/ klasörü henüz commit edilmedi.
---

## Faz 3: Mimari Dokümantasyon (`akis-aciklama.md`)

**Amaç:** Akışın mimarisini, başlangıç şablonunu, şablona göre yapılan iyileştirmeleri ve üretim ortamı yol haritasını profesyonel Türkçe ile belgelemek.

**Verilen kısıtlar:**

- Şablon adı ve linkinin yer alması; #4640 şablonunun neden mimari temel olarak seçildiğinin açıklanması.
- Veri akışının adım adım anlatılması: Schedule → Sayfalama → Float dönüşümü → Kayıt → Fark tespiti → Bildirim → Hata dalı.
- Proxy rotasyonu, IP bazlı hız sınırlama ve headless browser (Puppeteer) ihtiyacının ele alınması.

**Doğrulama:**

- Dokümandaki tüm sayısal iddialar (20 sayfa, 117 ürün, 48 kontrol, `?page=99` davranışı) doğrulama çıktılarıyla karşılaştırılmıştır.
- Zorunlu başlıkların varlığı otomatik olarak kontrol edilmiştir.

*PROMPT:* (Section A düzeltmeleri ile birlikte)
Act as a Principal Automation Engineer. Let's implement the Section A Bonus feature and finalize the Turkish documentation for Section B.

Task 1: Section A Bonus Implementation (`/products/search`)
1. In `A-mesaj-otomasyonu/process_messages.py`, enhance the handling for `urun-sorusu` and `fiyat` categories:
   - Extract key product keywords from incoming messages (e.g., "serum", "krem", "tonik", "retinol", "c vitamini", "güneş kremi" / "sunscreen").
   - Query the DummyJSON product search API: `GET https://dummyjson.com/products/search?q={keyword}`.
   - If results are returned, pick the top relevant match and dynamically incorporate its title and current price into `cevap_taslagi`.
   - If no products match or the search yields empty items, gracefully keep the professional generic customer assistance response.
2. Re-run `process_messages.py` using `.\.venv\Scripts\python.exe` to update `A-mesaj-otomasyonu/talepler.json`.
3. Re-run `generate_summary_html.py` to keep `ozet.html` in sync with the enriched responses.
4. Run `validate_talepler.py` and ensure all 15 records remain valid with no regressions.

Task 2: Translate and Localize `B-n8n/akis-aciklama.md` into Turkish
1. Translate and restructure `B-n8n/akis-aciklama.md` completely into professional, high-grade Turkish.
2. Ensure it comprehensively covers:
   - Başlangıç Şablonu: Resmî n8n kütüphanesindeki "Competitor price monitoring with web scraping, Google Sheets & Telegram (#4640)" şablonunun adı ve linki (ve brief'teki 1884 linkinin 404 vermesi sebebiyle neden buna geçildiği).
   - Veri Akışı ve Adımlar: Schedule (09:00) -> Sayfalama Döngüsü (?page=N ve rel="next" bitiş kontrolü) -> Veri Çıkarma & $ işaretinden arındırılmış sayısal (float) fiyat dönüşümü -> Google Sheets zaman damgalı kayıt -> Fark/Değişiklik tespiti -> Telegram bildirimi -> Hata Dalı (Stop and Error + Kritik Alarm).
   - Şablona Göre Yapılan Mimari İyileştirmeler: Sayfalama mantığının eklenmesi, ?page=99 boş sayfa senaryosunun defansif olarak yakalanması, hata yakalama mimarisi.
   - Üretim Ortamı (Production) Yol Haritası: Proxy rotasyonu, IP rate limiting, headless browser (Puppeteer) ihtiyacı.

Execute the scripts, run the validation checks, and verify both deliverables.

*OUTPUT:* (Section A düzeltmeleri ile birlikte)
İki görev de tamamlandı. Script'ler çalıştırıldı, talepler.json ve ozet.html güncellendi, validate_talepler.py 15 kaydın hepsini geçerli buldu. workflow.json doğrulayıcısı da hâlâ 48/48 geçiyor.

Görev 1: /products/search bonusu

Önemli bir kısıt ortaya çıktı: DummyJSON katalogunda gerçek bir kozmetik serisi yok. serum, retinol, vitamin c, toner ve sunscreen aramaları hiç sonuç döndürmüyor. Arama ayrıca çok gevşek çalışıyor; cream araması "Ice Cream" (market ürünü) ve açıklamasında "creamy" geçen bir rujla eşleşiyor. İlk sonucu doğrudan almak, krem soran müşteriye dondurma fiyatı yazdırabilirdi. Bu yüzden process_messages.py içindeki eşleştirmeye üç koruma ekledim:

Terim çevirisi: Türkçe terimler İngilizce arama terimlerine çevriliyor (örneğin güneş kremi → sunscreen, c vitamini → vitamin c, nemlendirici → moisturizer / moisture, krem → cream).
Eşleşme filtresi: Yalnızca beauty ve skin-care kategorisindeki, terimin başlıkta ya da açıklamada tam kelime olarak geçtiği ürünler kabul ediliyor.
Genele düşmeme: Mesajda özel bir terim varsa (retinol gibi) genel terime (serum) geri düşülmüyor. Retinol serumu soran müşteriye alakasız bir serum sunmak yanıltıcı olurdu.
Arama başarısız olursa, API hata verirse ya da uygun eşleşme bulunmazsa kibar genel yanıt korunuyor. Hangi terimin arandığı ve sonucu not alanına yazılıyor, böylece yanıtı gözden geçiren kişi eşleşmeyi kontrol edebiliyor.

Bu kısıt nedeniyle gerçek veride yalnızca #10 zenginleşti. "Nemlendirici krem ne kadar?" sorusu "Olay Ultra Moisture Shea Butter Body Wash — $12.99" ürünüyle eşleşti. Ürün bir vücut şampuanı olduğu için, müşteriye göndermeden önce bu eşleşmenin uygun olup olmadığına bakmak isteyebilirsin. #9, #11 ve #13'te katalogda karşılık olmadığından genel yanıt kaldı.

Kayıtları eski çıktıyla alan alan karşılaştırdım. 1–8 ve 12 değişmedi; kategoriler, devret alanları, IDOR güvenlik kaydı (#1) ve istenmeyen etki / iade devirleri aynı kaldı. Karşılaştırmada bir kusur da buldum ve düzelttim: #10 ürün bilgisini verdiği halde sonuna "Ürün sorunuzla ilgili bilgiyi ekibimiz ayrıca paylaşacaktır" satırı ekleniyordu.

Arama fonksiyonu dışarıdan enjekte edildiği için sahte aramayla şu uç durumları da test ettim; hepsi geçti:

API'nin 503 döndürmesi;
boş sonuç;
"Ice Cream" ve "creamy" filtresi;
özel terimden genel terime düşülmemesi;
İngilizce mesaj;
istenmeyen etki mesajında ürün adı hiç yazılmaması.
Görev 2: B-n8n/akis-aciklama.md Türkçe

Senin sadeleştirdiğin İngilizce sürümü temel alarak dokümanı baştan Türkçe yazdım ve istediğin bölüm yapısına göre düzenledim:

Başlangıç Şablonu: #4640 şablonunun adı ve linki, 1884 linkinin neden kullanılmadığı.
Veri Akışı ve Adımlar: 09:00 zamanlaması, sayfalama ve rel="next" bitiş kontrolü, $416.99 → 416.99 dönüşümü, zaman damgalı kayıt, fark tespiti, Telegram bildirimi ve Stop and Error ile kritik alarmı içeren hata dalı.
Şablona Göre Yapılan Mimari İyileştirmeler: sayfalamanın eklenmesi, ?page=99 senaryosuna karşı katmanlı savunma, hata yakalama mimarisi ve karşılaştırmalı bir özet tablo.
Üretim Ortamı Yol Haritası: proxy rotasyonu, IP bazlı hız sınırlama ve headless browser (Puppeteer) ihtiyacı.
Node adları workflow.json'daki adlarla eşleşsin diye İngilizce bıraktım.

Değişiklikler henüz commit edilmedi. Bir de __pycache__/process_messages.cpython-313.pyc dosyası git'te izleniyor; bu tür derleme çıktılarını .gitignore'a eklemek iyi olur.

**!!! SON TESLİMATA DAİR PROMPTLAR @A-claude-code.md dosyasındadır**

## Faz 4: Kural 4 İnisiyatifleri — HTTP Yeniden Deneme (Retry Resilience) Mimarisi

*PROMPT:*

Act as a Principal Automation Engineer. Let's finish the final polish on `feature/advanced-initiatives`:

1. CSV Semicolon Delimiter:
   - In `process_messages.py` and in `ozet.html` client-side export script, switch the CSV delimiter from comma (`,`) to semicolon (`;`).
   - Keep UTF-8 BOM encoding intact so double-clicking on Turkish regional Excel opens columns properly separated.

2. Initiative 3 (n8n Resilience & Retry Logic):
   - In `B-n8n/build_workflow.py` and `B-n8n/workflow.json`, update the HTTP Request node configuration for page scraping:
     Add retry resilience properties:
     `"retryOnFail": true`, `"maxTries": 3`, `"waitBetweenTries": 2000`.
   - Update `B-n8n/akis-aciklama.md` under the architectural improvements section with a brief mention of this 3-attempt backoff retry logic.

3. Re-run and Update Artifacts:
   - Re-run `process_messages.py` to regenerate `talepler.csv`.
   - Re-run `generate_summary_html.py`.
   - Re-run `validate_workflow.py` and refresh `B-n8n/execution_report.txt`.
   - Ensure all validations pass cleanly.


   *OUTPUT:*
   Üç madde de tamamlandı ve tüm doğrulamalar geçti. Yeniden ürettiğim her şey feature/advanced-initiatives dalında; henüz commit etmedim.

1. CSV ayırıcısı artık noktalı virgül (;)

process_messages.py içine tek bir CSV_DELIMITER = ";" sabiti ekledim. Dosya yazımı, validator ve panodaki indirme betiği bu sabiti kullanıyor, yani üçü aynı ayırıcıda kalıyor.
Panoda noktalı virgül içeren hücreler artık tırnak içine alınıyor.
talepler.csv hâlâ UTF-8 BOM ile başlıyor ve başlık satırı id;kanal;musteri_id;konu;oncelik;devret;cevap_taslagi;not.
Validator dosyayı ; ile okuyup talepler.json ile satır satır karşılaştırıyor; 15 kayıt geçti.
Pano betiğinin sözdizimini node --check ile doğruladım. İndirme butonunu bu değişiklikten sonra tarayıcıda yeniden tıklayarak test etmedim; değişiklik sadece ayırıcı karakteri.
2. n8n yeniden deneme ayarları

retryOnFail: true ve maxTries: 3 zaten tanımlıydı. Değişen tek değer bekleme süresi: waitBetweenTries 3000 ms'den 2000 ms'ye indi.
workflow.json elle düzenlenmedi, build_workflow.py ile yeniden üretildi.
validate_workflow.py eskiden sadece "en az 2 deneme" kontrol ediyordu. Artık tam olarak 3 deneme ve 2000 ms bekleme şart. Kural sayısı 48'de kaldı.
İki metin hatasını da düzelttim. maxTries: 3 toplam 3 deneme demek (ilk istek artı 2 yeniden deneme), ama iş akışındaki not kutusu "3 retries", doküman da "3 kez yeniden denenir" diyordu. İkisi de "toplam 3 deneme, 2 saniye arayla" olarak güncellendi.
Dokümanla ilgili bir not: İstekte "backoff" denmişti, ama n8n'in yerleşik yeniden denemesi sabit aralıklı. Denemeler arası süre artmıyor, hep 2 saniye. akis-aciklama.md §4.3'te bunu açıkça yazdım ve süresi artan (üstel) bekleme gerekirse §7.2'deki yol haritasına yönlendirdim. README'deki CSV açıklamalarına da noktalı virgül bilgisini ekledim.

3. Yeniden üretilen dosyalar

Adım	Sonuç
process_messages.py
15 kayıt, talepler.json ve talepler.csv yazıldı
generate_summary_html.py
ozet.html 15 satırla üretildi
validate_talepler.py
JSON ve CSV doğrulaması geçti
validate_workflow.py
48 geçti, 0 başarısız; execution_report.txt UTF-8 olarak yenilendi
Çalıştırma sırasında terminalde bir an görünen -1 çıkış kodları script hatası değil. Çıktıyı kısaltmak için kullandığım PowerShell komutundan kaynaklanıyordu. Kısaltmadan tekrar çalıştırınca iki script de 0 ile çıktı.