# Bölüm B – n8n Fiyat Takip Akışı: Prompt Denetim Kaydı

## Mühendislik ve AI Orkestrasyon Metodolojisi

Bu kayıt, Bölüm B teslimatının (n8n iş akışı ve mimari dokümanı) yapay zekâ destekli olarak nasıl tasarlandığını, üretildiğini ve doğrulandığını belgelemektedir. Çalışma boyunca üç temel ilke uygulanmıştır:

1. **AI-assisted engineering:** 3 saatlik kısıtlı süre zarfında kurumsal ve hatasız bir mimari teslim edebilmek için yapay zekâ, bir mimari planlama ve hızlandırma aracı olarak kullanılmıştır. Topoloji, hata politikası ve kabul kriterleri mühendis tarafından belirlenmiş; yapay zekâ bu çerçeve içinde uygulama hızını artırmıştır.
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
- **Değerlendirme ve revizyonlar:** Yapay zekâ çıktısında tespit edilen ve düzeltilen noktalar.
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

**Değerlendirme ve revizyonlar:**

- Brief'te önerilen `n8n.io/workflows/1884-web-scraper-and-email-notification/` adresinin **404** döndürdüğü, 1884 numaralı şablonun şablon API'sinde de bulunmadığı tespit edilmiştir. Var olmayan bir kaynağa atıf yapmak yerine en yakın gerçek şablon seçilmiştir: [#4640 – Competitor price monitoring with web scraping, Google Sheets & Telegram](https://n8n.io/workflows/4640-competitor-price-monitoring-with-web-scrapinggoogle-sheets-and-telegram/).

<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->

---

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

**Değerlendirme ve revizyonlar:**

- IF ve Filter node'ları, #4640 şablonundaki güncel şemayla uyumlu olması için v2.2 sürümüne yükseltilmiştir.
- İlk çalıştırmada ~117 ürünün tamamı için "yeni ürün" alarmı gönderilmesini önlemek amacıyla `is_baseline_run` bayrağı eklenmiştir.
- Kontrollü hata dalı ile global Error Trigger'ın aynı hata için iki kez alarm üretmesi engellenmiştir: *Abort Execution* kaynaklı hatalar global dalda yok sayılır.

<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->

---

## Faz 3: Mimari Dokümantasyon (`akis-aciklama.md`)

**Amaç:** Akışın mimarisini, başlangıç şablonunu, şablona göre yapılan iyileştirmeleri ve üretim ortamı yol haritasını profesyonel Türkçe ile belgelemek.

**Verilen kısıtlar:**

- Şablon adı ve linkinin yer alması; 1884 linkinin neden kullanılmadığının açıklanması.
- Veri akışının adım adım anlatılması: Schedule → Sayfalama → Float dönüşümü → Kayıt → Fark tespiti → Bildirim → Hata dalı.
- Proxy rotasyonu, IP bazlı hız sınırlama ve headless browser (Puppeteer) ihtiyacının ele alınması.

**Doğrulama:**

- Dokümandaki tüm sayısal iddialar (20 sayfa, 117 ürün, 48 kontrol, `?page=99` davranışı) doğrulama çıktılarıyla karşılaştırılmıştır.
- Zorunlu başlıkların varlığı otomatik olarak kontrol edilmiştir.

**Değerlendirme ve revizyonlar:**

- Doküman önce İngilizce yazılmıştır. Proje kuralları güncellendikten sonra Türkçe olarak yeniden yapılandırılmıştır. Node adları, `workflow.json` ile birebir eşleşmesi için İngilizce bırakılmıştır.

<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->
