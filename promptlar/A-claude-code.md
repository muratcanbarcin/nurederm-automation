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

**Değerlendirme ve revizyonlar:**

<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->

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

**Değerlendirme ve revizyonlar:**

<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->

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

<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->

---

## Faz 4: Teslim Hazırlığı ve Depo Hijyeni

**Amaç:** Depoyu teslime hazır hâle getirmek ve Türkçe kök dokümantasyonu yazmak.

**Kapsam:**

- `.gitignore` ile bytecode, sanal ortam, gizli bilgi, işletim sistemi ve IDE dosyalarının dışlanması.
- İzlenen `__pycache__` dosyasının index'ten çıkarılması.
- Kök `README.md` dokümanının yazılması.

**Değerlendirme ve revizyonlar:**

- Brief'te mesaj #1 için "sepet_userId=2" değeri verilmiştir. Canlı API çıktısı ve `talepler.json` kaydı ise 12 numaralı sepetin `userId=12` kullanıcısına ait olduğunu göstermektedir. Dokümantasyona doğrulanmış değer yazılmıştır.

<!-- [KULLANICI PROMPTU VE ÇIKTISI BURAYA EKLENECEK] -->
