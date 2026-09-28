# Bölüm A – Müşteri Mesajı Otomasyonu: Prompt Denetim Kaydı

## Mühendislik ve AI Orkestrasyon Metodolojisi

Bu kayıt, Bölüm A teslimatının yapay zekâ destekli olarak nasıl planlandığını, üretildiğini ve doğrulandığını belgelemektedir. Çalışma boyunca üç temel ilke uygulanmıştır:

1. **AI-assisted engineering:** 3 saatlik kısıtlı süre zarfında kurumsal ve hatasız bir mimari teslim edebilmek için yapay zekâ, bir mimari planlama ve hızlandırma aracı olarak kullanılmıştır. Mimari kararlar, güvenlik politikaları ve kabul kriterleri mühendis tarafından belirlenmiş; yapay zekâ bu çerçeve içinde uygulama hızını artırmıştır.
2. **Görev ayrıştırma (task decomposition) ve meta-prompting:** Kontrolsüz tek bir prompt yerine görevler modüler parçalara ayrılmıştır. Her fazda rol tanımı, çıktı formatı, güvenlik kısıtları ve doğrulama beklentileri açıkça verilmiştir. Kalıcı kurallar (`.cursorrules`) aracılığıyla şu kısıtlar tüm oturumlara taşınmıştır: IDOR koruması, tıbbi/hukuki devir zorunluluğu, İngilizce kod ve Türkçe dokümantasyon.
3. **Doğrula, sonra kabul et:** Üretilen hiçbir mantık doğrudan kabul edilmemiştir. Her çıktı şu yöntemlerle adım adım doğrulanmış ve gerektiğinde revize edilmiştir:
   - uç durum (edge case) senaryoları;
   - sahte (mock) arama ve sepet fonksiyonları;
   - DummyJSON'a yapılan canlı HTTP istekleri;
   - `validate_talepler.py` validasyon script'i;
   - tarayıcıda `ozet.html` üzerinde UI etkileşimi.

### Kayıt formatı

Her faz aşağıdaki yapıyı izler:

- **Amaç:** Fazın iş hedefi.
- **Verilen kısıtlar:** Prompt'a eklenen teknik ve güvenlik sınırları.
- **Doğrulama:** Çıktının nasıl test edildiği.
- **Değerlendirme ve revizyonlar:** Yapay zekâ çıktısında tespit edilen ve düzeltilen noktalar.
- **Ham prompt ve çıktı:** Oturum kaydının orijinal (İngilizce) hâli.

---

## Faz 1: Çekirdek Mantık & IDOR Koruması

**Amaç:** `mesajlar.json`'daki 15 müşteri mesajını sınıflandırmak (`urun-sorusu`, `fiyat`, `siparis-durumu`, `iade-sikayet`, `istenmeyen-etki`, `diger`), yanıt taslağı üretmek ve sonucu katı şemalı `talepler.json` olarak yazmak.

**Verilen kısıtlar:**

- Python 3.11+, tip tanımlı modeller (Pydantic) ve sorumlulukların ayrıştırılması.
- `istenmeyen-etki` ve `iade-sikayet` kategorilerinde her koşulda `devret: true`; teşhis veya ürün önerisi kesinlikle yok.
- `siparis-durumu` kategorisinde sipariş numarası ayrıştırılır ve `https://dummyjson.com/carts/{id}` sorgulanır. `cart.userId != musteri_id` ise:
  - yetkisiz erişim işaretlenir;
  - sepet içeriği gizlenir;
  - `devret: true` atanır;
  - `SECURITY:` önekli bir not yazılır.
- HTTP 404 yanıtında müşteriden sipariş numarasını kontrol etmesi kibarca istenir.

**Doğrulama:**

- Canlı DummyJSON istekleri. Mesaj #1'de müşteri 7'nin, `userId=12` kullanıcısına ait 12 numaralı siparişi sorguladığı tespit edilmiş, sipariş içeriği gizlenmiştir.
- Mesaj #3'teki 9999 numaralı sipariş için 404 senaryosu.
- İngilizce mesaj (#6) için dil tespiti.
- Tek mesajda birden fazla niyet (#8: fiyat + sipariş) için ikincil niyet ekleme mantığı.
- Spam / şüpheli link tespiti (#7).
- `validate_talepler.py` ile şema, benzersiz kimlik, zorunlu devir ve güvenlik ihlali kuralları.

*PROMPT:*
Act as a Principal Software Engineer. Let's execute Phase 1 of our automation project.
Requirements:
1. Verify the project directory structure and create missing folders:
   - A-mesaj-otomasyonu/
   - B-n8n/
   - promptlar/
2. Ensure `A-mesaj-otomasyonu/mesajlar.json` exists. If a Python virtual environment is not set up, configure one and install required dependencies (`requests`, `pydantic`).
3. Create `A-mesaj-otomasyonu/process_messages.py` entirely in English (clean code, typed, modular functions).
   Business Logic to implement:
   - Load 15 messages from `mesajlar.json`.
   - Classification: Assign one category to each message among:
     `urun-sorusu`, `fiyat`, `siparis-durumu`, `iade-sikayet`, `istenmeyen-etki`, `diger`.
   - Safety Barrier: For `iade-sikayet` and `istenmeyen-etki`, strictly set `devret: true`. Draft a polite human-handoff response without medical advice or product suggestions.
   - Order Status & IDOR Security Check (`siparis-durumu`):
     * Extract order ID using regex.
     * Query DummyJSON API: GET https://dummyjson.com/carts/{order_id}.
     * CRITICAL SECURITY: Compare `cart['userId']` with `musteri_id`.
       - If they do NOT match: Set `devret: true`, conceal cart details, draft an unauthorized access warning response, and add a note explaining potential IDOR / customer mismatch.
       - If they match: Set `devret: false`, include product titles, quantities, and total amount in `cevap_taslagi`.
       - If API returns 404 (Not Found): Set a friendly not-found draft response with `devret: false`.
   - General queries: Handle `urun-sorusu`, `fiyat`, and `diger` appropriately.
4. Execute `python A-mesaj-otomasyonu/process_messages.py` via terminal to generate `A-mesaj-otomasyonu/talepler.json`.
5. Run a validation test on `talepler.json` ensuring all 15 records exist with keys `{id, konu, devret, cevap_taslagi, not}` and print an executive summary in the console showing category distribution, handoff count, and security violation detections.

*OUTPUT:*
1. Faz tamamlandı. talepler.json 15 kayıtla oluşturuldu ve doğrulamadan geçti. Sistem bir IDOR vakası yakaladı: 1 numaralı mesajda 7 numaralı müşteri, 12 numaralı kullanıcıya ait 12 numaralı siparişi sordu. Sipariş içeriği gizlendi ve talep insana devredildi.
Doğrulama çıktısının özeti

Kategori	Adet
siparis-durumu
5
urun-sorusu
4
fiyat
2
diger
2
iade-sikayet
1
istenmeyen-etki
1
İnsana devredilen: 3 kayıt (1, 4 ve 5 numaralı mesajlar).
Güvenlik ihlali: 1 kayıt (1 numaralı mesaj).
Kontrol edilenler: 15 kaydın hepsinde tam olarak {id, konu, devret, cevap_taslagi, not} anahtarları var, id'ler girdiyle aynı ve tekrar etmiyor. iade-sikayet, istenmeyen-etki ve güvenlik ihlali içeren kayıtların hepsinde devret: true.
Sipariş kontrolleri (DummyJSON)

Sahiplik doğrulananlar: 2, 6 ve 8 numaralı mesajlarda sepetin sahibi müşterinin kendisi. Yanıt taslağına ürünler, adetler ve toplam tutar (indirimli tutarla birlikte) yazıldı.
Bulunamayan sipariş: 3 numaralı mesajdaki 9999 numaralı sipariş 404 döndü. Müşteriye kibar bir "sipariş bulunamadı" yanıtı hazırlandı ve talep devredilmedi (devret: false).
IDOR yanıtı: Taslak, siparişin var olup olmadığını ya da kime ait olduğunu açık etmiyor; yalnızca kimlik doğrulaması gerektiğini söylüyor. Ayrıntılar yalnızca iç kullanıma yönelik not alanında.
Yol boyunca verdiğim kararlar

Python sürümü: Varsayılan python 3.9.12 (Anaconda) olduğu ve kural 3.11+ istediği için sanal ortamı Python 3.13 ile kurdum. Betikleri .\.venv\Scripts\python.exe ile çalıştırın; düz python komutu 3.9'u kullanır.
Çok niyetli mesaj: 8 numaralı mesajda hem sipariş hem fiyat sorusu var. Ana kategori siparis-durumu oldu, fiyat sorusu taslağa ek bir cümle ve nota ikincil niyet olarak eklendi.
Spam: 7 numaralı mesaj (takipçi satışı ve bit.ly linki) diger olarak sınıflandı; taslakta yanıt gönderilmemesi gerektiği yazıyor.
Kargo sorusu: 12 numaralı mesaj ("hangi kargo firması") belirli bir siparişle ilgili olmadığından diger oldu.
Dil: 6 numaralı mesaj İngilizce olduğu için taslağı da İngilizce hazırlandı.
Fiyat ve ürün yanıtları: Elimizde ürün kataloğu olmadığından bu taslaklar uydurma bilgi vermiyor; genel bir yanıt veriyor ve not alanında gönderilmeden önce resmi verilerle kontrol edilmesi gerektiği yazıyor.
Notların dili: Proje kuralı gereği not alanı İngilizce. Müşteriye gidecek taslaklar Türkçe (6 numaralı mesaj hariç).
Oluşturulan ve değişen dosyalar

B-n8n/ ve promptlar/ klasörleri ile .venv/ sanal ortamı (requests 2.34, pydantic 2.13).
A-mesaj-otomasyonu/process_messages.py: Sınıflandırma, güvenlik kontrolleri, API sorgusu ve yanıt taslakları. Hata durumunda 3 kez yeniden deneyip zaman aşımı uyguluyor; API'ye ulaşılamazsa talebi devrediyor.
A-mesaj-otomasyonu/validate_talepler.py: Çıktıyı doğrulayıp yukarıdaki özeti konsola basıyor.
A-mesaj-otomasyonu/talepler.json: Üretilen çıktı.
Tekrar çalıştırmak için:

.\.venv\Scripts\python.exe A-mesaj-otomasyonu/process_messages.py
.\.venv\Scripts\python.exe A-mesaj-otomasyonu/validate_talepler.py
---

## Faz 2: HTML Yönetici Panosu (`ozet.html`)

**Amaç:** `talepler.json` verisinden yöneticilere yönelik, tek sayfalık, Türkçe ve Tailwind CDN tabanlı bir özet panosu üretmek.

**Verilen kısıtlar:**

- Arayüz metinlerinin tamamı profesyonel Türkçe.
- Tüm metriklerin (toplam mesaj, insana devredilen talepler, güvenlik ihlalleri) ve kategori dağılımının veriden dinamik olarak üretilmesi; sabit sayı kullanılmaması.
- İngilizce dahili notların (ör. `SECURITY:` notu) panoda Türkçe olarak gösterilmesi.
- Kullanıcı verisinin HTML kaçışından geçirilmesi.

**Doğrulama:**

- `generate_summary_html.py` ile üretim ve kayıt sayısının (15 satır) kontrolü.
- Tarayıcıda şu etkileşimlerin kontrolü:
  - "Tümü", "İnsana Devredilenler" ve "Doğrudan Yanıtlananlar" filtreleri;
  - güvenlik ihlali rozetinin görünürlüğü;
  - boş durum mesajı.

*PROMPT:*
Act as a Senior Frontend & Automation Engineer. Let's execute Phase 2: Generating the HTML Summary Dashboard.

Objective:
Create a Python script `A-mesaj-otomasyonu/generate_summary_html.py` that reads both `A-mesaj-otomasyonu/mesajlar.json` and `A-mesaj-otomasyonu/talepler.json`, and outputs a self-contained, elegant single-page dashboard at `A-mesaj-otomasyonu/ozet.html`.

UI/UX & Business Requirements:
1. Language: The entire user interface MUST be in Turkish (kurumsal, profesyonel üslup).
2. Design & Styling:
   - Use Tailwind CSS via CDN (`https://cdn.tailwindcss.com`).
   - Clean enterprise aesthetic (Slate/Zinc neutral background, modern cards, clear typography).
   - Fully responsive, standalone (double-clickable in any browser without needing a running server).
3. Header & Metric Cards (Executive Overview):
   - Total Messages Processed (15).
   - Human Handoffs Required (count of devret=true, red/amber badge).
   - Security Violations / IDOR Prevented (1 detected, prominent alert card).
   - Category Breakdown pills/cards with exact counts: siparis-durumu, urun-sorusu, fiyat, diger, iade-sikayet, istenmeyen-etki.
4. Detailed Requests Table:
   - Columns: ID, Kanal (WhatsApp/Instagram with icon/badge), Müşteri ID, Konu (color-coded badge), Durum (Devret: İnsana Yönlendir / Otomatik Yanıt), Cevap Taslağı, Dahili Not.
   - Distinct visual highlighting for:
     * Unauthorized IDOR record (ID: 1) -> Highlight with a red/amber border or security alert badge.
     * Sensitive topics (ID: 4, 5) -> Distinct caution styling.
5. Interactive Polish (Vanilla JS embedded):
   - Simple tab or filter buttons: "Tümü (15)", "İnsana Devredilenler (3)", "Doğrudan Yanıtlananlar (12)".

Execution:
1. Create and execute `generate_summary_html.py` using our virtual environment (`.\.venv\Scripts\python.exe`).
2. Verify that `A-mesaj-otomasyonu/ozet.html` is generated properly and valid.

*OUTPUT:*
2. Faz tamamlandı. generate_summary_html.py betiği ozet.html panosunu oluşturuyor; sayfayı tarayıcıda açıp kontrol ettim, filtreler de doğru çalışıyor.


Kontrol sonuçları

HTML yapısı: Açılıp kapanmayan etiket yok ve şablonda doldurulmadan kalan değişken yok.
Satırlar: Tabloda 15 satır var; 3'ü insana devredilen, 12'si otomatik yanıt.
Filtreler: "İnsana Devredilenler (3)" seçilince yalnızca 1, 4 ve 5 numaralı talepler görünüyor. Diğer iki buton da doğru sayıları gösteriyor.
Görsel kontrol: Tailwind CDN yükleniyor, üst kartlar ve vurgular düzgün. Bu kontrol sırasında iki küçük düzeni düzelttim: "Aksiyon Gerekli" rozeti başlığa yapışıyordu, "Müşteri ID" başlığı da iki satıra kırılıyordu.
Panoda neler var

Üst kartlar:
İşlenen toplam mesaj: 15.
İnsana devredilen talepler: 3, amber renkli "Aksiyon Gerekli" rozetiyle.
Kırmızı güvenlik kartı: 1 IDOR vakası ve ayrıntısı.
Kategori dağılımı: İstediğiniz sırada altı kart; her kartta adet ve yüzde çubuğu var.
Satır vurguları:
1 numaralı talep: kırmızı sol kenarlık ve "Güvenlik İhlali" rozeti.
4 ve 5 numaralı talepler: amber sol kenarlık ve "Hassas Konu" rozeti.
Verdiğim kararlar

Dahili notların dili: talepler.json içindeki notlar proje kuralı gereği İngilizce. Arayüz tamamen Türkçe olsun diye betik, bilinen not kalıplarını ekranda Türkçeye çeviriyor; JSON dosyası değişmiyor. İleride process_messages.py içindeki not metinleri değişirse o not panoda İngilizce görünür, sayfa bozulmaz. Şu an tanınmayan not yok.
Kategori ve güvenlik tanımları: Betik bunları doğrudan process_messages.py dosyasından alıyor, yani iki betik birbiriyle tutarlı kalıyor. Bu yüzden betiği .venv içindeki Python ile çalıştırmanız gerekiyor.
Sayfaya çift tıklayınca sunucu olmadan açılıyor. Yalnızca Tailwind CDN'den yüklendiği için ilk açılışta internet bağlantısı gerekiyor. Yeniden oluşturmak için:

.\.venv\Scripts\python.exe A-mesaj-otomasyonu/generate_summary_html.py
---

## Faz 3: Bonus Ürün Arama Entegrasyonu (`/products/search`)

**Amaç:** `urun-sorusu` ve `fiyat` kategorilerinde mesajdaki kozmetik anahtar kelimeleri çıkarmak, `https://dummyjson.com/products/search?q={terim}` ile katalogda aramak ve eşleşen ürünün adı ve fiyatıyla yanıt taslağını zenginleştirmek.

**Verilen kısıtlar:**

- Eşleşme bulunamazsa veya API hata verirse kibar standart yanıta geri dönülmesi.
- Tıbbi güvenlik kuralının korunması: ürünün cilde uygunluğu hakkında yorum yapılmaması.

**Doğrulama:**

- Canlı keşif araması. DummyJSON katalogunda `serum`, `retinol`, `vitamin c`, `toner` ve `sunscreen` için hiç sonuç olmadığı görülmüştür. `cream` araması ise "Ice Cream" (market) ve açıklamasında "creamy" geçen bir rujla eşleşmektedir.
- Sahte arama fonksiyonuyla şu uç durumlar test edilmiştir:
  - API 503 hatası;
  - boş sonuç;
  - "Ice Cream" / "creamy" eleme;
  - özel terimden genel terime düşülmemesi;
  - İngilizce mesaj;
  - istenmeyen etki mesajında ürün adının hiç yazılmaması.
- Önceki `talepler.json` ile alan alan karşılaştırma (regresyon kontrolü) ve `validate_talepler.py` ile 15/15 geçerlilik.

**Değerlendirme ve revizyonlar:**

- "İlk sonucu al" yaklaşımı reddedilmiştir. Bunun yerine iki filtre eklenmiştir:
  - yalnızca `beauty` ve `skin-care` kategorilerindeki ürünler kabul edilir;
  - terim, başlıkta ya da açıklamada tam kelime olarak geçmelidir.
- Mesajda özel bir terim (retinol, C vitamini, güneş kremi) varsa genel terime (serum, krem) geri düşülmemesi kuralı getirilmiştir. Retinol serumu soran müşteriye alakasız bir serum sunulması yanıltıcı olurdu.
- Regresyon karşılaştırmasında, zenginleştirilmiş fiyat yanıtının (#10) sonuna gereksiz bir "ürün sorunuzla ilgili bilgiyi ayrıca paylaşacağız" satırı eklendiği tespit edilmiştir. Bunun üzerine taslağın zaten kapsadığı ikincil niyetleri (`covered_intents`) tekrarlamayan bir düzeltme yapılmıştır.

**Ham prompt ve çıktı:**

*PROMPT:* (Section B düzeltmeleri ile birlikte)
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

*OUTPUT:* (Section B düzeltmeleri ile birlikte)
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
---

## Faz 4: Teslim Hazırlığı ve Depo Hijyeni

**Amaç:** Depoyu teslime hazır hâle getirmek ve Türkçe kök dokümantasyonu yazmak.

**Kapsam:**

- `.gitignore` ile bytecode, sanal ortam, gizli bilgi, işletim sistemi ve IDE dosyalarının dışlanması.
- İzlenen `__pycache__` dosyasının index'ten çıkarılması.
- Kök `README.md` dokümanının yazılması.

**Değerlendirme ve revizyonlar:**

- Brief'te mesaj #1 için "sepet_userId=2" değeri verilmiştir. Canlı API çıktısı ve `talepler.json` kaydı ise 12 numaralı sepetin `userId=12` kullanıcısına ait olduğunu göstermektedir. Dokümantasyona doğrulanmış değer yazılmıştır.

*PROMPT:*
Act as a Principal Software Engineer. Let's execute the final delivery phase: secure repository hygiene, prepare structured prompt logs with Turkish methodology explanations, and author the root README.md.

Task 1: Repository Hygiene & .gitignore
1. Update `.gitignore` to strictly exclude:
   - `__pycache__/` and `*.pyc`
   - `.venv/` and any virtualenv directories
   - `.env` and sensitive credential files
   - `.DS_Store`, `Thumbs.db`
   - `.cursor/` local workspace logs and caches
2. Run `git rm --cached -r __pycache__` (if already tracked) to ensure no bytecode artifacts remain in staging.

Task 2: Prompt Audit Logs (`promptlar/A-claude-code.md` & `promptlar/B-n8n.md`)
1. In both files, write a comprehensive, professional Turkish header titled:
   "Mühendislik ve AI Orkestrasyon Metodolojisi"
   Include the following points:
   - 3 saatlik kısıtlı süre zarfında kurumsal ve hatasız bir mimari teslim edebilmek için yapay zekâ bir mimari planlama ve hızlandırma aracı (AI-assisted engineering) olarak kullanılmıştır.
   - Kontrolsüz tek bir prompt yerine, görevler modüler parçalara (task decomposition) ayrılmış ve meta-prompting yöntemiyle kısıtlar verilmiştir.
   - Üretilen her mantık doğrudan kabul edilmemiş; uç durumlar (edge cases), sahte aramalar, canlı HTTP istekleri, Python validasyon scriptleri (validate_talepler, validate_workflow) ve tarayıcıda UI etkileşimiyle adım adım doğrulanıp revize edilmiştir.
2. Structure the files with clear Turkish section headers (Faz 1: Çekirdek Mantık & IDOR, Faz 2: HTML Pano, Faz 3: Bonus Arama Entegrasyonu vb.).
3. Leave clearly marked placeholder blocks for raw prompts:
   `<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->`
   so the exact session logs can be pasted without disrupting the narrative.

Task 3: Root `README.md` (Executive Turkish Documentation)
Write an executive, production-grade `README.md` in Turkish covering:
- Proje Özeti, Başlama ve Bitiş Saati: 28 Eylül 2026, 14:00 - 16:45 (~2 saat 45 dk).
- Proje Mimarisi: Dizin yapısı ağacı ve dosya görevleri.
- Bölüm A (Müşteri Mesajı Otomasyonu):
  * Kurulum ve tek komutla çalıştırma talimatı (`.\.venv\Scripts\python.exe A-mesaj-otomasyonu/process_messages.py` ve `generate_summary_html.py`).
  * Güvenlik & IDOR Koruması: Mesaj #1'deki müşteri_id=7 / sepet_userId=2 tutarsızlığının tespiti, sepet verisinin gizlenmesi ve `devret: true` kararı.
  * Tıbbi Güvenlik: İstenmeyen etki ve iade konularında teşhis konulmadan uzman temsilciye devir prensibi.
  * Bonus Ürün Arama Entegrasyonu: DummyJSON katalog kısıtları, "Ice Cream" vb. gürültüleri elemek için eklenen kategori (beauty, skin-care) ve kelime eşleşme filtreleri.
  * ozet.html Dashboard: Metrik kartları, filtreler ve güvenlik rozetleri.
- Bölüm B (n8n Fiyat Takip Akışı):
  * Başlangıç Şablonu: #4640 numaralı resmî n8n şablonu ve linki (1884 linkinin 404 dönmesi üzerine yapılan gerçekçi düzeltme).
  * 20 sayfalık `rel="next"` ve `maxPages: 50` döngüsü (?page=99 boş sayfa açığına karşı defansif mimari).
  * Fiyatın float sayıya dönüştürülmesi ($ işareti temizliği), ISO zaman damgası, Google Sheets kaydı, Telegram bildirimleri ve hata dalı (Stop and Error + Kritik Alarm).
- Test ve Doğrulama Metodolojisi:
  * `validate_talepler.py` (15/15 kayıt doğrulaması) ve `validate_workflow.py` (48/48 kural doğrulaması).
  * Manuel kontroller ve UI doğrulama adımları.

Execute the tasks, verify that the repository status is clean, and confirm when ready.

*OUTPUT:*
Depo teslime hazır. Üç görev tamamlandı ve ffacdf6 commit'iyle kaydedildi; git status temiz. Commit etmemi açıkça istememiştin, ama "repo durumu temiz olmalı" şartı ancak commit ile sağlanabiliyordu. İstersen git reset --soft HEAD~1 ile geri alabilirsin.

Görev 1: Depo hijyeni

Yeni .gitignore şunları dışlıyor: __pycache__/, *.pyc, .venv/ ve diğer sanal ortam klasörleri, .env ve kimlik bilgisi dosyaları (*.pem, credentials*.json vb.), .DS_Store, Thumbs.db, .cursor/. Her kalıbı git check-ignore ile test ettim.
İzlenen .pyc dosyası kökte değil A-mesaj-otomasyonu/__pycache__/ altındaydı; git rm --cached komutunu o yola uyguladım. Git'te bytecode, venv ya da gizli bilgi dosyası kalmadı.
README'deki kurulum komutu (pip install -r requirements.txt) çalışabilsin diye requirements.txt ekledim. İçinde pydantic, requests ve urllib3 var.
Görev 2: Prompt kayıtları (promptlar/A-claude-code.md, promptlar/B-n8n.md)

İki dosyada da "Mühendislik ve AI Orkestrasyon Metodolojisi" başlığı ve istediğin üç ilke yer alıyor.
Anlatı faz bazlı ve Türkçe. Bölüm A'da Faz 1 Çekirdek Mantık & IDOR, Faz 2 HTML Pano, Faz 3 Bonus Arama, Faz 4 Teslim; Bölüm B'de Faz 1 Keşif & Şablon, Faz 2 workflow.json, Faz 3 Dokümantasyon.
Her fazın sonunda, ham oturum kayıtları için <!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] --> yer tutucusu duruyor.
Faz 1 ve Faz 2'nin (A) "Değerlendirme ve revizyonlar" bölümlerini boş bıraktım; o oturumlarda hangi düzeltmelerin yapıldığını bilmiyorum. Diğer fazlarda bu bölümler gerçekten yaşanan bulgularla dolu: 1884 linkinin 404 vermesi, ?page=99 senaryosu, "Ice Cream" eşleşmesi, tekrarlanan ikincil niyet satırı.
Görev 3: README.md İstediğin tüm başlıklar var: zaman çizelgesi, dizin ağacı, Bölüm A'nın beş konusu, Bölüm B'nin başlıkları, doğrulama metodolojisi ve manuel UI adımları. İçerikte iki düzeltme yaptım:

IDOR değeri: Brief'te mesaj #1 için "sepet_userId=2" yazıyor, fakat talepler.json'daki kayıt 12 numaralı sepetin sahibini userId=12 gösteriyor. README'ye bu değeri yazdım ve farkı bir notla açıkladım. Güvenlik kararı her iki değerde de aynı.
Bitiş saati: README'deki 16:45, istediğin gibi planlanan bitiş saati. Şu an saat 15:1x; farklı bir saatte bitirirsen güncellemen gerekir.
Doğrulama

README'deki komutları kök dizinden aynen çalıştırdım. validate_talepler.py 15/15, validate_workflow.py 48/48 geçti.
Metodolojide geçen tarayıcı doğrulamasını da gerçekten yaptım. Panoyu yerel bir sunucudan açtım:
metrik kartları 15 / 3 / 1 gösteriyor;
"İnsana Devredilenler" filtresi yalnızca #1, #4 ve #5'i, "Doğrudan Yanıtlananlar" kalan 12 kaydı gösteriyor, "Tümü" hepsini geri getiriyor;
#1 satırında güvenlik rozeti var ve sepet içeriği sızmıyor.


## Faz 4: Kural 4 İnisiyatifleri — Öncelik Puanlaması ve CSV Entegrasyonu

**Ham prompt ve çıktı:**
*PROMPT:*

Act as a Principal Automation & Integration Engineer. We are implementing Rule 4 initiatives for Section A on branch `feature/advanced-initiatives`.

Objectives:
1. Operational Priority Scoring (A-mesaj-otomasyonu/process_messages.py):
   - Add a deterministic `oncelik` field to each processed message:
     * "YUKSEK" (High): For `istenmeyen-etki` (patient safety risks) and IDOR security mismatch (#1).
     * "ORTA" (Medium): For `iade-sikayet` and unverified/not-found order queries (#3).
     * "DUSUK" (Low): For routine inquiries (`urun-sorusu`, `fiyat`, `diger`).
   - Reflect this in the schema and output dictionary.

2. CSV Export Pipeline:
   - In `process_messages.py`, add a function to export the processed records into `A-mesaj-otomasyonu/talepler.csv` with standard UTF-8 BOM encoding (for clean Excel compatibility).
   - Columns: id, kanal, musteri_id, konu, oncelik, devret, cevap_taslagi, not.

3. Frontend Dashboard Updates (A-mesaj-otomasyonu/generate_summary_html.py):
   - Update `ozet.html` generation:
     * Add a Priority column in the table displaying color-coded badges (Red for YÜKSEK, Amber for ORTA, Green for DÜŞÜK).
     * Add an executive metric card at the top: "Yüksek Öncelikli Vakalar" with count.
     * Add an interactive "CSV Olarak İndir" button in the dashboard toolbar that triggers a download of the currently visible/filtered rows as a CSV file using pure client-side JavaScript.

4. Execution & Validation:
   - Run `process_messages.py` using `.\.venv\Scripts\python.exe`.
   - Run `generate_summary_html.py` to rebuild the dashboard.
   - Run `validate_talepler.py` and ensure backward compatibility (all 15 items still validate cleanly).
   - Generate `B-n8n/execution_report.txt` by running `.\.venv\Scripts\python.exe B-n8n/validate_workflow.py`.


*OUTPUT:*

Dört hedefin hepsi feature/advanced-initiatives dalında tamamlandı ve tüm doğrulamalar geçti: 15 kayıt temiz doğrulanıyor, CSV dışa aktarımı talepler.json ile satır satır eşleşiyor ve n8n raporu 48/48 geçti. Hiçbir şey commit edilmedi.

1. Öncelik puanlaması (process_messages.py) Öncelik iki adımda belirleniyor. Önce kategori bir taban değer veriyor. Ardından sipariş sorgusunun sonucu bu değeri yalnızca yükseltebiliyor. Canlı çalıştırmadaki sonuç:

Öncelik	Kayıtlar
YUKSEK
#1 (IDOR uyuşmazlığı), #4 (istenmeyen etki)
ORTA
#3 (bulunamayan sipariş, HTTP 404), #5 (iade)
DUSUK
Diğer 11 kayıt
oncelik alanı TicketResult şemasına eklendi ve JSON'da konu'nun hemen ardından geliyor. JSON'daki tek değişiklik bu alanın eklenmesi; kategori, devret, yanıt ve not alanları aynı kaldı.

2. CSV dışa aktarımı export_csv() kayıtları mesajlar.json ile birleştirip talepler.csv dosyasına istenen sütun sırasıyla yazıyor. Dosya UTF-8 BOM ile kodlanıyor (dosyanın ilk baytları EF BB BF). Çok satırlı yanıt taslakları doğru şekilde tırnak içine alınıyor.

3. Pano (ozet.html)

Tabloya renk kodlu "Öncelik" sütunu eklendi: kırmızı YÜKSEK, amber ORTA, yeşil DÜŞÜK.
Üstte "Yüksek Öncelikli Vakalar" kartı var: sayı 2, altında #1 ve #4 listeleniyor.
"CSV Olarak İndir" butonu, o anda görünen satırları tamamen tarayıcı tarafında indiriyor. Tarayıcıda test ettim: "İnsana Devredilenler" filtresinde yalnızca #1, #4 ve #5 geldi, dosya adı talepler-insana-devredilenler.csv oldu, BOM vardı ve Türkçe karakterler bozulmadı. Görünür satır yoksa buton devre dışı kalıyor.
Tabloda öncelik rozetleri

4. Doğrulama validate_talepler.py anahtarları birebir karşılaştırıyordu, bu yüzden oncelik eklenince doğrulama kırılacaktı. Validator'ı şöyle güncelledim:

oncelik opsiyonel. Güncellemeden önce eski formatlı dosyayı da doğrulattım, sorunsuz geçti.
Alan varsa şu kurallar uygulanıyor: istenmeyen etki ve güvenlik ihlali YUKSEK, iade en az ORTA olmalı. Bu kuralların bozulduğu ve KRITIK gibi geçersiz bir değer girildiği test kayıtlarını hepsini yakaladı.
CSV'nin BOM'u, başlığı ve JSON ile satır satır eşleşmesi de kontrol ediliyor.
B-n8n/execution_report.txt UTF-8 olarak üretildi. PowerShell'in > yönlendirmesi dosyayı UTF-16 yazacağı için çıktıyı cmd üzerinden yönlendirdim. README'de artık yanlış olan şema cümlesini düzelttim; öncelik tablosunu ve CSV ile pano açıklamalarını ekledim.

Kararınızı bekleyen iki konu:

Sipariş numarası olmayan sipariş soruları DÜŞÜK sayılıyor. Brief'teki "doğrulanamayan" ifadesini 404 ve API hatası olarak yorumladım; bunlar ORTA. Numarasız soruyu da ORTA saymak isterseniz tek satırlık bir değişiklik.
CSV virgülle ayrılmış. Türkçe bölge ayarlı Excel ise noktalı virgül bekler. Dosyaya çift tıklayınca tüm veri tek sütuna düşebilir; Excel'deki "Veri > Metinden" içe aktarımında sorun olmaz. İsterseniz ayırıcıyı ; yapabilirim.

