# Mevcut Analize Göre En Mantıklı 10 Oyun

Bu rapor, `20261003T204134704Z-d8d2b3` kimlikli kayıtlı run'dan (large scan, 10 catalog pages, W=48) üretildi. Tarama 2026-10-03 tarihinde başladı, enrichment ve analysis aşamaları en son 2026-10-12 tarihinde tamamlandı.
Tüm sayılar saklanan veriden türetildi, yeni bir ağ isteği yapılmadı. Yeniden üretmek için
`python scripts/build_top10_report.py --db data/analyses.db` çalıştırılır.

**Veri sürümü.** Sonuçlar `parameters_version = e5e095876f70` ile saklanan analize aittir. Aynı run'ın enrichment ve analysis aşamaları 2026-10-12 tarihinde yeniden çalıştırıldı.
Ana çalışma klasöründeki `config/parameters.toml` dosyası, o tarihte bir yazılım türü dışlama listesi (`enrichment.exclusions.software_genres`) ve `max_cluster_share = 0.15` ayarı içeriyordu.
Bu ayarların sonuçlara ayrı ayrı katkısı bu raporda ölçülmedi. Önceki bir analiz sürümüyle yapılacak karşılaştırmalarda sonuçlar aynı parametrelerle üretilmemiş olabilir.

## 1. Özet

On oyun, run'ın 1,187 oyunluk basit alt kümesinden seçildi (karmaşıklık skoru C en düşük %40'ta).
Her biri son 48 ay içinde çıkmış, fırsat skoru Ω pozitif bir arketipe ait, ücretli, Early Access'ten çıkmış ve
olumlu yorum oranı en az %80. Sıralama FORMULATION §5'teki çaba-ayarlı getiri E'ye göre yapıldı ve arketip başına en fazla iki oyun alındı.

- Seçim 5 arketipi kapsıyor: Funny, Platformer, Mystery, FPS, Retro. Seçimdeki arketipler arasında en yüksek Ω değerleri FPS (+2.00) ve Retro (+0.78).
- On oyun birlikte yaklaşık 8.44M tahmini adet ve $103.63M tahmini net gelire karşılık geliyor. Bu gelirin %54'i tek bir oyundan (DELTARUNE) geliyor ve bu oyun olmadan toplam $47.27M olur. Toplamlar bu nedenle tek bir oyunun etkisinde.
- Seçimin medyan liste fiyatı $10.87, medyan C değeri 0.227. Seçimin çekildiği 96 oyunluk havuzun medyan C değeri 0.263.
- On oyunun içinde 6 oyun kendi yayıncısı (geliştirici ve yayıncı alanları aynı), 2 oyun tek dil listeliyor. Bu durum, geniş yerelleştirmenin bu sonuçlar için bir ön koşul olmamış olabileceğini düşündürüyor.
- Yorum tabanlı adet tahmini 3 oyunda SteamSpy sahip bandının içinde, 3 oyunda üstünde, 4 oyunda altında kalıyor. Tahminler sıralama sinyali olarak tutarlı görünüyor ancak satış rakamı olarak alıntılanmamalı (§7).
- Seçimin dayandığı arketipler küçük (her biri 9 ile 24 oyun arasında). Ω değerleri daha büyük bir örneklemle belirgin biçimde değişebilir, bu yüzden arketip düzeyindeki çıkarımlar oyun düzeyindeki gözlemlerden daha zayıf.

## 2. Veri ve Seçim Kuralı

Run'da 2,967 zenginleştirilmiş oyun var. SteamSpy toplu listesi sahip sayısına göre sıralı ve burada kullanılan 10 katalog sayfası
50,000–100,000 sahip bandında bitiyor. Dolayısıyla run'daki her oyun en az bu kitle büyüklüğüne ulaşmış bir oyun ve bu,
talep skorlarının nasıl okunabileceğini etkiliyor (§7).

![Seçim hunisi](rapor_assets/fig01_selection_funnel.png)

Seçim kuralı yalnızca pipeline'ın zaten ürettiği nicelikleri kullanıyor.

1. **Basit alt küme.** C, run'ın 40. yüzdeliğinde veya altında (0.322), FORMULATION §3a'da kilitlendiği gibi.
2. **Yakın tarihli.** 2022-10-03 veya sonrasında çıkmış (run başlangıcından 48 ay önce, FORMULATION §6'daki pencere W).
3. **Ω > 0 olan puanlanmış arketip.** Etiketi "Utilities / Software" ile başlayan yazılım benzeri küme varsa çıkarılır. Bu run'ın arketip matrisinde yazılım benzeri bir küme kalmadı (todo.md madde 9).
4. **Ücretli, tamamlanmış, iyi karşılanmış.** Ücretsiz oyunların gelir tahmini yok, Early Access oyunlar bitmemiş ve %80'in altındaki olumlu yorum oranı ürün kalitesi için zayıf kanıt sayıldı.
5. **Sıralama.** Çaba-ayarlı getiri E = R_net / (C + 0.05). Tek bir arketip listeyi doldurmasın diye arketip başına en fazla 2 oyun.

Havuzun Ω > 0 arketiplerle sınırlanması projenin araştırma sorusunu izliyor: talebin yüksek, rekabetin düşük olduğu yerler nerede?
Diğer arketiplerin en güçlü oyunları kaybolmasın diye §6'da ayrıca listelendi.

## 3. Arketip Bağlamı

![Arketip haritası](rapor_assets/fig02_archetype_map.png)

| Arketip | Oyun | D | K | Σ | Ω | Medyan tahmini adet | Medyan C | Tek oyunculu / çok oyunculu / co-op payı | Seçilen oyunlar |
|---|---|---|---|---|---|---|---|---|---|
| Funny / Stylized / Hand-drawn | 24 | +1.77 | -0.24 | -0.67 | +0.58 | 62,504 | 0.275 | %66 / %39 / %26 | DELTARUNE, Pizza Tower |
| Platformer / 2D Platformer / Side Scroller | 19 | +0.96 | -0.49 | +0.06 | +0.55 | 43,845 | 0.262 | %84 / %18 / %18 | ANIMAL WELL, SANABI |
| Mystery / Point & Click / Investigation | 21 | -0.69 | -0.39 | +1.03 | +0.15 | 6,100 | 0.245 | %49 / %10 / %4 | SIGNALIS, Duck Detective: The Secret Salami |
| FPS / Difficult / Violent | 9 | +2.29 | -0.99 | +2.63 | +2.00 | 74,250 | 0.217 | %73 / %24 / %22 | GoreBox, Void Stranger |
| Retro / Old School / 1990's | 13 | +0.62 | -0.79 | +0.97 | +0.78 | 36,100 | 0.246 | %77 / %27 / %4 | HROT, Shipwrecked 64 |

D, K ve Σ sırasıyla medyan tahmini adedin, penceredeki çıkış sayısının ve bir eksi medyan C'nin z-skorlarıdır. Ω = 0.40·D − 0.30·K + 0.30·Σ (FORMULATION §6).

![Oyuncu modu payları](rapor_assets/fig09_mode_shares.png)

Bu seçimdeki arketipler ağırlıklı olarak tek oyunculu. Çok oyunculu payı %10'un üzerinde olan arketipler yalnızca Funny (%39), Platformer (%18), Mystery (%10), FPS (%24) ve Retro (%27).

![Arketip satış trendi](rapor_assets/fig07_archetype_trends.png)

Her nokta en fazla altı oyunun medyanıdır, dolayısıyla çizgiler yalnızca betimleyicidir. FORMULATION §6, bu eğimlere anlamlılık iddiası bağlanmadığını belirtiyor.

## 4. On Oyuna Genel Bakış

| # | Oyun | Arketip | Çıkış | Fiyat | Yorum (olumlu) | Tahmini adet (orta) | Tahmini net gelir | C | E (M) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | DELTARUNE | Funny | 2025-06 | $24.99 | 87,082 (%98) | 3.22M | $56.36M | 0.307 | 158.1 |
| 2 | Pizza Tower | Funny | 2023-01 | $13.39 | 45,503 (%98) | 2.28M | $21.32M | 0.237 | 74.3 |
| 3 | ANIMAL WELL | Platformer | 2024-05 | $17.49 | 13,049 (%95) | 652k | $7.99M | 0.162 | 37.7 |
| 4 | SIGNALIS | Mystery | 2022-10 | $13.99 | 21,517 (%97) | 1.08M | $10.54M | 0.239 | 36.5 |
| 5 | GoreBox | FPS | 2023-07 | $8.99 | 8,322 (%88) | 416k | $2.62M | 0.217 | 9.8 |
| 6 | SANABI | Platformer | 2023-11 | $9.74 | 4,789 (%95) | 239k | $1.63M | 0.262 | 5.2 |
| 7 | HROT | Retro | 2023-05 | $6.79 | 3,794 (%96) | 190k | $902k | 0.185 | 3.8 |
| 8 | Duck Detective: The Secret Salami | Mystery | 2024-05 | $7.49 | 4,840 (%95) | 179k | $939k | 0.203 | 3.7 |
| 9 | Void Stranger | FPS | 2023-09 | $11.99 | 2,833 (%91) | 105k | $880k | 0.217 | 3.3 |
| 10 | Shipwrecked 64 | Retro | 2024-01 | $7.99 | 2,179 (%95) | 81k | $451k | 0.246 | 1.5 |

![Karmaşıklık ve gelir](rapor_assets/fig03_complexity_vs_revenue.png)

![Yüzdelik profili](rapor_assets/fig06_percentile_profile.png)

Yüzdelik sütunları her oyunu 96 oyunluk havuzla karşılaştırır. Karmaşıklık sütununda yüksek yüzdelik daha karmaşık bir oyun anlamına gelir.

![Fiyat ve hacim](rapor_assets/fig08_price_vs_sales.png)

![Aylık ortalama adet](rapor_assets/fig05_sales_per_month.png)

Aylık ortalama, yaşam boyu tahmini adedi çıkıştan beri geçen aya böler. Satışların çıkışta yoğunlaşan olağan eğrisini gizler, bu yüzden eski oyunlar güncel hızlarından daha yavaş görünür.

![Satış tahmini ve sahip bandı](rapor_assets/fig04_sales_vs_owners.png)

## 5. Oyun Oyun Analiz

### 1. DELTARUNE

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | tobyfox / tobyfox | Çıkış | Jun 4, 2025 (run'dan 16 ay önce) |
| Arketip (Ω) | Funny (+0.58, 24 oyun) | Liste fiyatı | $24.99 |
| Yorum sayısı / olumlu oran | 87,082 / %98.3 | Tahmini adet düşük / orta / yüksek | 2.61M / 3.22M / 3.92M |
| Tahmini net gelir | $56.36M | Çaba-ayarlı getiri E | 158.1M |
| Karmaşıklık skoru C | 0.307 (1,187 basit oyun içinde 86. yüzdelik, 96 oyunluk havuzda 84.) | SteamSpy sahip bandı | 1,000,000 .. 2,000,000, Boxleiter orta tahmini bandın **üstünde** |
| Aylık ortalama adet | 201,791 | Kurulum boyutu / asgari RAM | 1.0 GB / 2.0 GB |
| Dil / başarım / DLC / platform sayısı | 2 / yok / 1 / 2 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Story Rich (1715), Great Soundtrack (1685), Pixel Graphics (1664), Funny (1553), RPG (1487), Singleplayer (1369), Bullet Hell (1284), 2D (1135).

Oyunun taşıdığı arketip etiket tag'leri: Funny (1553), Stylized (kayıtlı tag'ler arasında yok), Hand-drawn (kayıtlı tag'ler arasında yok). Karmaşıklık skorunda tahmini (imputed) girdiler: achievement_count.

- Havuzun en yüksek tahmini net gelirine (yaklaşık $56.4M) ve en yüksek E değerine sahip. Tahmini 3.22M adedi Funny arketipinin medyanının (62,505 adet) yaklaşık 51 katı, yani arketipin tipik bir üyesi değil.
- $24.99 fiyatla havuzun 99. yüzdeliğinde, 87,082 yorumla (%98.3 olumlu) yorum sayısında birinci. Orta tahmin SteamSpy bandının (1M ile 2M) üzerinde, dolayısıyla gelir olduğundan yüksek olabilir.
- C değeri 0.307 ile havuzda 84. yüzdelikte, seçimin en yüksek C değeri ve basit alt küme eşiğinin (0.322) hemen altında. Başarım sayısı saklanan veride eksikti ve tahmin edilerek (imputed) dolduruldu.
- Geliştiricinin saklanan veride bir başka başlığı var (dev_title_count = 1). Genel bilgiye göre bu, geliştiricinin daha önce çok büyük bir kitleye ulaşmış bir oyunun devamı. Veri önceden var olan kitlenin payını ayıramıyor, ancak bu sonuca katkıda bulunmuş olabilir.
- En çok oy alan tag'ler Story Rich (1,715 oy), Great Soundtrack, Pixel Graphics, Funny ve RPG. Arketipin etiket tag'lerinden yalnızca Funny'yi taşıyor.

**Küçük bir ekip açısından okuma.** Mevcut bir kitlesi olmayan küçük bir ekip için doğrudan bir şablon olması olası değil. Listedeki toplamları ve sıralamayı belirgin biçimde yukarı çekiyor, bu yüzden özetteki toplamlar bu oyun olmadan da okunmalı (§6).

### 2. Pizza Tower

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | Tour De Pizza / Tour De Pizza | Çıkış | Jan 26, 2023 (run'dan 44 ay önce) |
| Arketip (Ω) | Funny (+0.58, 24 oyun) | Liste fiyatı | $13.39 |
| Yorum sayısı / olumlu oran | 45,503 / %98.4 | Tahmini adet düşük / orta / yüksek | 1.82M / 2.28M / 2.96M |
| Tahmini net gelir | $21.32M | Çaba-ayarlı getiri E | 74.3M |
| Karmaşıklık skoru C | 0.237 (1,187 basit oyun içinde 37. yüzdelik, 96 oyunluk havuzda 32.) | SteamSpy sahip bandı | 1,000,000 .. 2,000,000, Boxleiter orta tahmini bandın **üstünde** |
| Aylık ortalama adet | 51,449 | Kurulum boyutu / asgari RAM | 300 MB / 512 MB |
| Dil / başarım / DLC / platform sayısı | 12 / 74 / 1 / 1 | Oyuncu modları (Steam kategorileri) | Single-player, Multi-player, Co-op |

En çok oy alan tag'ler: Great Soundtrack (980), 2D Platformer (913), Fast-Paced (855), Indie (838), Cartoony (813), Platformer (671), Funny (661), Singleplayer (631).

Oyunun taşıdığı arketip etiket tag'leri: Funny (661), Stylized (kayıtlı tag'ler arasında yok), Hand-drawn (kayıtlı tag'ler arasında yok).

- Havuzun ikinci en yüksek tahmini net gelirine (yaklaşık $21.3M) sahip ve C değeri 0.237. Havuzda 32. yüzdelik, yani düşük uçta değil. Konumu çok düşük bir karmaşıklık skorundan değil, hacimden geliyor.
- Tahmini 2.28M adedi, Funny arketipinin medyanının (62,505 adet) yaklaşık 36 katı. Arketipin talep skoru bir medyan olduğu için tipik bir üyeyi anlatmıyor.
- Boxleiter orta tahmini SteamSpy sahip bandının (1M ile 2M) üzerinde kalıyor, bu yüzden gelir rakamı olduğundan yüksek olabilir.
- En çok oy alan tag'ler Great Soundtrack (980 oy), 2D Platformer, Fast-Paced, Cartoony ve Funny. Veri, müziğin, sanat stilinin ve oynanışın oyunun karşılanmasındaki payını ayıramıyor.
- $13.39 fiyatı havuzun 87. yüzdeliğinde ve oyun yine de yorum sayısında üst yüzdelikte (99.). Bu, oyuna olan talebin fiyatla güçlü biçimde sınırlanmamış olabileceğini düşündürüyor.

**Küçük bir ekip açısından okuma.** Güçlü bir ses ve görsel kimliği olan stilize bir 2D platform oyununun orta bir fiyatla geniş bir kitleye ulaşabileceğini gösteriyor olabilir. Kendi arketipinde medyanın çok üzerinde kaldığı için şablon olarak alınırsa hayatta kalma yanlılığı riski taşıyor.

### 3. ANIMAL WELL

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | Billy Basso / Bigmode | Çıkış | May 9, 2024 (run'dan 29 ay önce) |
| Arketip (Ω) | Platformer (+0.55, 19 oyun) | Liste fiyatı | $17.49 |
| Yorum sayısı / olumlu oran | 13,049 / %95.3 | Tahmini adet düşük / orta / yüksek | 522k / 652k / 848k |
| Tahmini net gelir | $7.99M | Çaba-ayarlı getiri E | 37.7M |
| Karmaşıklık skoru C | 0.162 (1,187 basit oyun içinde 7. yüzdelik, 96 oyunluk havuzda 3.) | SteamSpy sahip bandı | 200,000 .. 500,000, Boxleiter orta tahmini bandın **üstünde** |
| Aylık ortalama adet | 22,644 | Kurulum boyutu / asgari RAM | 35 MB / 1.0 GB |
| Dil / başarım / DLC / platform sayısı | 11 / 20 / 0 / 1 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Metroidvania (303), Exploration (297), Puzzle (263), Pixel Graphics (258), Puzzle-Platformer (257), Horror (217), Platformer (211), 2D (203).

Oyunun taşıdığı arketip etiket tag'leri: Platformer (211), 2D Platformer (kayıtlı tag'ler arasında yok), Side Scroller (kayıtlı tag'ler arasında yok).

- 35 MB kurulum boyutu havuzun 1. yüzdeliğinde ve 0.162'lik düşük C değerinin (havuzda 3. yüzdelik) ana nedeni. Kurulum boyutu varlıkların nasıl üretildiğine ve sıkıştırıldığına da bağlı olduğu için bu büyük olasılıkla üretim eforunu yansıtmıyor.
- $17.49 ile fiyatta 94. yüzdelikte, 13,049 yorumla ve %95.3 olumlu. Yani bu arketipte premium bir fiyat güçlü bir karşılanmayla bağdaşmış.
- 652k adetlik orta tahmin SteamSpy bandının (200k ile 500k) üzerinde, dolayısıyla gerçek rakam banda daha yakın olabilir. Platformer arketipinin medyanının (43,845 adet) yaklaşık 15 katı.
- Yayıncısı Bigmode, yani kendi yayıncısı değil. Arketipinin üç etiket tag'inden yalnızca birini (Platformer) taşıyor, en çok oy alan tag'leri Metroidvania, Exploration ve Puzzle.

**Küçük bir ekip açısından okuma.** Ticari sonuç veride net, ancak C değeri on oyun içinde en az güvenilir olanı. Düşük eforlu bir şablondan çok, premium fiyatlı bir puzzle-platformer'ın iyi satabileceğinin kanıtı olarak okunması daha uygun.

### 4. SIGNALIS

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | rose-engine / Balor Games | Çıkış | Oct 27, 2022 (run'dan 47 ay önce) |
| Arketip (Ω) | Mystery (+0.15, 21 oyun) | Liste fiyatı | $13.99 |
| Yorum sayısı / olumlu oran | 21,517 / %96.8 | Tahmini adet düşük / orta / yüksek | 861k / 1.08M / 1.40M |
| Tahmini net gelir | $10.54M | Çaba-ayarlı getiri E | 36.5M |
| Karmaşıklık skoru C | 0.239 (1,187 basit oyun içinde 37. yüzdelik, 96 oyunluk havuzda 34.) | SteamSpy sahip bandı | 1,000,000 .. 2,000,000, Boxleiter orta tahmini bandın **içinde** |
| Aylık ortalama adet | 22,788 | Kurulum boyutu / asgari RAM | 2.0 GB / 4.0 GB |
| Dil / başarım / DLC / platform sayısı | 8 / 13 / 0 / 1 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Survival Horror (940), Psychological Horror (855), Female Protagonist (833), Sci-fi (783), Atmospheric (758), Lovecraftian (636), Dark (608), Mystery (598).

Oyunun taşıdığı arketip etiket tag'leri: Mystery (598), Point & Click (kayıtlı tag'ler arasında yok), Investigation (kayıtlı tag'ler arasında yok).

- Geliştirici (rose-engine) ve yayıncı (Balor Games) farklı, yani kendi yayıncısı olan bir sonuç değil.
- $13.99 fiyatla 21,517 yorumu (%96.8 olumlu) ve tahmini 1.08M adedi var. Orta tahmin SteamSpy bandının (1M ile 2M) içinde, bu yüzden en çok doğrulanan tahminlerden biri.
- C değeri 0.239 (havuzda 34. yüzdelik). Kurulum boyutu 2 GB (havuzda 80. yüzdelik), 8 dil ve 13 başarım listeliyor.
- En çok oy alan tag'ler Survival Horror (940 oy), Psychological Horror (855), Female Protagonist, Sci-fi ve Lovecraftian. Oyun yine de Mystery / Point & Click / Investigation arketipine atanmış ve bu arketipin etiket tag'lerinden yalnızca Mystery'yi (598 oy) taşıyor, dolayısıyla arketipe uyumu gevşek.
- Tahmini adedi arketipin medyanının (6,100 adet) yaklaşık 176 katı. Arketipin Ω değeri (+0.15) bu oyunu anlatmıyor, çünkü oyun arketipin tipik bir üyesi değil.
- Çıkış tarihi (2022-10-27) 48 aylık pencerenin başlangıcına (2022-10-03) çok yakın.

**Küçük bir ekip açısından okuma.** Veri, tür kimliği net bir korku oyununun premium fiyatla büyük bir kitleye ulaşabileceğini düşündürüyor. Arketip skoru bu sonucun nedeni olarak okunmamalı.

### 5. GoreBox

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | F2Games / F2Games | Çıkış | Jul 21, 2023 (run'dan 38 ay önce) |
| Arketip (Ω) | FPS (+2.00, 9 oyun) | Liste fiyatı | $8.99 |
| Yorum sayısı / olumlu oran | 8,322 / %88.1 | Tahmini adet düşük / orta / yüksek | 333k / 416k / 541k |
| Tahmini net gelir | $2.62M | Çaba-ayarlı getiri E | 9.8M |
| Karmaşıklık skoru C | 0.217 (1,187 basit oyun içinde 27. yüzdelik, 96 oyunluk havuzda 25.) | SteamSpy sahip bandı | 500,000 .. 1,000,000, Boxleiter orta tahmini bandın **altında** |
| Aylık ortalama adet | 10,825 | Kurulum boyutu / asgari RAM | 1.0 GB / 4.0 GB |
| Dil / başarım / DLC / platform sayısı | 1 / 24 / 0 / 1 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Gore (753), Sandbox (717), Violent (677), Physics (617), FPS (571), Shooter (553), PvE (519), Stylized (514).

Oyunun taşıdığı arketip etiket tag'leri: FPS (571), Difficult (kayıtlı tag'ler arasında yok), Violent (677).

- $8.99 fiyatla 8,322 yorumu ve tahmini 416k adedi var. Orta tahmin SteamSpy bandının (500k ile 1M) altında, bu da yorum tabanlı rakamın temkinli olabileceğini düşündürüyor.
- Olumlu yorum oranı %88.1 ile seçimin en düşüklerinden biri (havuzda 42. yüzdelik) ve %80 eşiğine en yakın oyunlardan biri.
- C değeri 0.217. Tek dil, 24 başarım listeliyor, kategorileri yalnızca Single-player ve bir seviye düzenleyicisi içeriyor. Geliştirici ve yayıncı aynı (F2Games).
- En çok oy alan tag'ler Gore (753 oy), Sandbox, Violent, Physics ve FPS. Yani oyun, tek bir mekanik fikir etrafında kurulu bir sandbox.
- FPS / Difficult / Violent arketipi 9 oyun içeriyor ve +2.00'lık Ω değeriyle seçimdeki en yüksek skor. Bu skor, medyanı 74,250 adet olan dokuz oyuna dayanıyor, dolayısıyla küçük örneklem nedeniyle kırılgan.

**Küçük bir ekip açısından okuma.** Veri, tek bir fikri ve fiziği öne çıkaran düşük kapsamlı bir sandbox oyununun orta fiyatla büyük bir kitleye ulaşabileceğini düşündürüyor. Daha düşük olumlu oran, kitlenin geniş ama daha az memnun olduğuna işaret ediyor olabilir.

### 6. SANABI

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | WONDER POTION / NEOWIZ | Çıkış | Nov 8, 2023 (run'dan 35 ay önce) |
| Arketip (Ω) | Platformer (+0.55, 19 oyun) | Liste fiyatı | $9.74 |
| Yorum sayısı / olumlu oran | 4,789 / %95.0 | Tahmini adet düşük / orta / yüksek | 192k / 239k / 311k |
| Tahmini net gelir | $1.63M | Çaba-ayarlı getiri E | 5.2M |
| Karmaşıklık skoru C | 0.262 (1,187 basit oyun içinde 52. yüzdelik, 96 oyunluk havuzda 49.) | SteamSpy sahip bandı | 500,000 .. 1,000,000, Boxleiter orta tahmini bandın **altında** |
| Aylık ortalama adet | 6,876 | Kurulum boyutu / asgari RAM | 1.0 GB / 4.0 GB |
| Dil / başarım / DLC / platform sayısı | 11 / 21 / 2 / 1 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Pixel Graphics (288), Story Rich (265), Action (247), Cyberpunk (221), Adventure (191), 2D Platformer (177), Singleplayer (166), Action-Adventure (165).

Oyunun taşıdığı arketip etiket tag'leri: Platformer (153), 2D Platformer (177), Side Scroller (83).

- Geliştirici (WONDER POTION) ve yayıncı (NEOWIZ) farklı, yani bu kendi yayıncısı olan bir sonuç değil.
- Tahmini 239k adet SteamSpy bandının (500k ile 1M) altında. Bu, yorum tabanlı rakamın temkinli olabileceğini ya da bandın kitleyi olduğundan büyük gösterdiğini düşündürüyor. Platformer arketipinin medyanının (43,845 adet) yaklaşık 5.5 katı.
- 11 dil ve 21 başarım listeliyor. 1 GB kurulum boyutu havuzun 48. yüzdeliğinde. C değeri 0.262.
- Tag'ler arasında Pixel Graphics, Story Rich ve Cyberpunk en çok oyu alıyor. Platformer arketipinin üç etiket tag'inin üçünü de taşıyor.

**Küçük bir ekip açısından okuma.** Yukarıdaki oyunlara göre daha geleneksel bir üretim profili var, yerelleştirme ve bir yayıncı içeriyor. Çok küçük, kendi kaynağıyla çalışan bir ekip için daha az doğrudan bir referans olabilir.

### 7. HROT

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | Spytihněv / Spytihněv | Çıkış | May 16, 2023 (run'dan 41 ay önce) |
| Arketip (Ω) | Retro (+0.78, 13 oyun) | Liste fiyatı | $6.79 |
| Yorum sayısı / olumlu oran | 3,794 / %96.1 | Tahmini adet düşük / orta / yüksek | 152k / 190k / 247k |
| Tahmini net gelir | $902k | Çaba-ayarlı getiri E | 3.8M |
| Karmaşıklık skoru C | 0.185 (1,187 basit oyun içinde 14. yüzdelik, 96 oyunluk havuzda 7.) | SteamSpy sahip bandı | 200,000 .. 500,000, Boxleiter orta tahmini bandın **altında** |
| Aylık ortalama adet | 4,672 | Kurulum boyutu / asgari RAM | 256 MB / 2.0 GB |
| Dil / başarım / DLC / platform sayısı | 2 / 55 / 0 / 1 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Retro (277), FPS (251), Shooter (169), Boomer Shooter (166), Indie (149), First-Person (149), Action (144), Singleplayer (143).

Oyunun taşıdığı arketip etiket tag'leri: Retro (277), Old School (136), 1990's (kayıtlı tag'ler arasında yok).

- $6.79 fiyatla 3,794 yorumu (%96.1 olumlu) ve tahmini 190k adedi var. Bu, Retro arketipinin medyanının (36,100 adet) yaklaşık 5 katı. Orta tahmin SteamSpy bandının (200k ile 500k) hemen altında, düşük-yüksek aralığı (152k ile 247k) ise bandla kesişiyor.
- C değeri 0.185 (havuzda 7. yüzdelik). 2 dil, 55 başarım, Steam Trading Cards ve uzun bir erişilebilirlik seçenekleri listesi var.
- En çok oy alan tag'ler Retro, FPS, Shooter ve Boomer Shooter. Yani kitlesi türü adıyla tanıyan, tanımlı bir nişte duruyor.
- Geliştirici ve yayıncı aynı isim, bu da kendi yayıncısı olduğu bir çıkışa işaret ediyor.

**Küçük bir ekip açısından okuma.** Mütevazı fiyatlı, kompakt bir retro nişancı oyunu. Veri, açıkça adlandırılmış bir nişin bu büyüklükte kendi yayıncısı olan bir çıkışı destekleyebileceğini düşündürüyor.

### 8. Duck Detective: The Secret Salami

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | Happy Broccoli Games / Happy Broccoli Games | Çıkış | May 23, 2024 (run'dan 28 ay önce) |
| Arketip (Ω) | Mystery (+0.15, 21 oyun) | Liste fiyatı | $7.49 |
| Yorum sayısı / olumlu oran | 4,840 / %95.0 | Tahmini adet düşük / orta / yüksek | 145k / 179k / 218k |
| Tahmini net gelir | $939k | Çaba-ayarlı getiri E | 3.7M |
| Karmaşıklık skoru C | 0.203 (1,187 basit oyun içinde 20. yüzdelik, 96 oyunluk havuzda 16.) | SteamSpy sahip bandı | 100,000 .. 200,000, Boxleiter orta tahmini bandın **içinde** |
| Aylık ortalama adet | 6,316 | Kurulum boyutu / asgari RAM | 500 MB / 1.0 GB |
| Dil / başarım / DLC / platform sayısı | 4 / 7 / 1 / 3 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Detective (131), Investigation (107), Casual (106), Short (98), Cute (96), Adventure (94), Noir (85), Mystery (83).

Oyunun taşıdığı arketip etiket tag'leri: Mystery (83), Point & Click (72), Investigation (107).

- $7.49 fiyatla 4,840 yorumu (%95.0 olumlu) ve tahmini 179k adedi var, bu SteamSpy bandının (100k ile 200k) içinde. Mystery / Point & Click arketipinin medyanının (6,100 adet) yaklaşık 29 katı.
- Bu arketipin Ω değeri +0.15 ile seçimdeki beş arketip içinde en zayıf pozitif skor. Yani oyun, zayıf desteklenen bir arketipin güçlü bir üyesi.
- Tag'ler arasında Detective, Investigation, Casual, Short (98 oy), Cute ve Noir var. Kısa süre, kapsamı küçük tutuyor olabilir.
- On oyun içinde üç platform listeleyen tek oyun ve 19 Steam kategori girdisi var, çoğu erişilebilirlik ve kontrolcü seçeneği. Yalnızca 7 başarımı ve 4 dili var.

**Küçük bir ekip açısından okuma.** Veri, kısa ve kapsamı sıkı tutulmuş bir anlatı oyununun orta ölçekli bir kitleye ulaşabileceğini düşündürüyor. Üç platformlu çıkış C değerini bir miktar yükseltiyor.

### 9. Void Stranger

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | System Erasure / System Erasure | Çıkış | Sep 1, 2023 (run'dan 37 ay önce) |
| Arketip (Ω) | FPS (+2.00, 9 oyun) | Liste fiyatı | $11.99 |
| Yorum sayısı / olumlu oran | 2,833 / %91.0 | Tahmini adet düşük / orta / yüksek | 85k / 105k / 127k |
| Tahmini net gelir | $880k | Çaba-ayarlı getiri E | 3.3M |
| Karmaşıklık skoru C | 0.217 (1,187 basit oyun içinde 27. yüzdelik, 96 oyunluk havuzda 23.) | SteamSpy sahip bandı | 100,000 .. 200,000, Boxleiter orta tahmini bandın **içinde** |
| Aylık ortalama adet | 2,828 | Kurulum boyutu / asgari RAM | 500 MB / 1.0 GB |
| Dil / başarım / DLC / platform sayısı | 2 / 1 / 1 / 1 | Oyuncu modları (Steam kategorileri) | Single-player |

En çok oy alan tag'ler: Mystery (91), Puzzle (88), Sokoban (80), Adventure (74), Singleplayer (69), 2D (66), Indie (62), Great Soundtrack (54).

Oyunun taşıdığı arketip etiket tag'leri: FPS (kayıtlı tag'ler arasında yok), Difficult (24), Violent (kayıtlı tag'ler arasında yok).

- Geliştirici ve yayıncı aynı (System Erasure). $11.99 fiyatla 2,833 yorumu (%91.0 olumlu) ve tahmini 105k adedi var. Orta tahmin SteamSpy bandının (100k ile 200k) alt sınırında.
- Yalnızca 1 başarım listeliyor ve 2 dili var. C değeri 0.217 (havuzda 23. yüzdelik).
- En çok oy alan tag'ler Mystery, Puzzle, Sokoban ve Adventure. Oyun FPS / Difficult / Violent arketipine atanmış ancak bu arketipin etiket tag'lerinden yalnızca Difficult'ı (24 oy) taşıyor, dolayısıyla atama gevşek ve oyun, arketipin dayandığı nişancı oyunlarına benzemiyor.
- Tahmini adedi arketipin medyanının (74,250 adet) yaklaşık 1.4 katı, yani arketipin tipik bir üyesi. E değeri düşük C ve $12 fiyattan geliyor, hacimden değil.

**Küçük bir ekip açısından okuma.** Arketip etiketi bu oyun için bilgi vermiyor. Oyunun kendi verisi, bir bulmaca-gizem oyununun mütevazı ama pozitif bir sonuç verebileceğini düşündürüyor.

### 10. Shipwrecked 64

| | | | |
|---|---|---|---|
| Geliştirici / yayıncı | Squeaks D'Corgeh / Cogware Games | Çıkış | Jan 1, 2024 (run'dan 33 ay önce) |
| Arketip (Ω) | Retro (+0.78, 13 oyun) | Liste fiyatı | $7.99 |
| Yorum sayısı / olumlu oran | 2,179 / %95.0 | Tahmini adet düşük / orta / yüksek | 65k / 81k / 98k |
| Tahmini net gelir | $451k | Çaba-ayarlı getiri E | 1.5M |
| Karmaşıklık skoru C | 0.246 (1,187 basit oyun içinde 42. yüzdelik, 96 oyunluk havuzda 41.) | SteamSpy sahip bandı | 200,000 .. 500,000, Boxleiter orta tahmini bandın **altında** |
| Aylık ortalama adet | 2,439 | Kurulum boyutu / asgari RAM | 2.0 GB / 8.0 GB |
| Dil / başarım / DLC / platform sayısı | 1 / 16 / 0 / 1 | Oyuncu modları (Steam kategorileri) | Single-player, Multi-player |

En çok oy alan tag'ler: Horror (223), Exploration (200), Puzzle (200), Psychological Horror (197), Platformer (189), 3D (185), Strategy (166), Story Rich (154).

Oyunun taşıdığı arketip etiket tag'leri: Retro (kayıtlı tag'ler arasında yok), Old School (kayıtlı tag'ler arasında yok), 1990's (146).

- Geliştirici (Squeaks D'Corgeh) ve yayıncı (Cogware Games) farklı. $7.99 fiyatla 2,179 yorumu (%95.0 olumlu) ve tahmini 80.6k adedi var. Orta tahmin SteamSpy bandının (200k ile 500k) altında.
- C değeri 0.246 (havuzda 41. yüzdelik) ile 2 GB kurulum boyutu (80. yüzdelik) ve 8 GB RAM gereksinimi var. Tek dil ve 16 başarım listeliyor.
- En çok oy alan tag'ler Horror, Exploration, Puzzle ve Psychological Horror. Retro arketipinin etiket tag'lerinden yalnızca 1990's'u (146 oy) taşıyor, bu yüzden arketipe uyumu kısmi.
- Tahmini adedi Retro arketipinin medyanının (36,100 adet) yaklaşık 2.2 katı. Tahmini net geliri yaklaşık $451k ile seçimdeki en küçük.

**Küçük bir ekip açısından okuma.** On oyun içinde en zayıf kanıtı taşıyor ve listede arketip başına iki oyun kuralı sayesinde yer alıyor. Mütevazı bir sonuç olarak okunmalı.


## 6. Duyarlılık ve Seçim Dışı Kalan Oyunlar

**Early Access.** Early Access oyunlara izin verilseydi Selaco ve Psycho Patrol R listeye girer,
Duck Detective: The Secret Salami ve Shipwrecked 64 listeden çıkardı. Girecek Early Access oyunların fiyatları Selaco ($24.99) ve Psycho Patrol R ($31.99) ve bunlar mevcut seçimin medyan fiyatının üzerinde.

**Ω ≤ 0 arketiplerde yüksek E'li oyunlar.** Bu oyunlar, arketipleri run'ın kendi ölçüsüne göre kalabalık veya düşük talepli olduğu için seçilmedi.
Bazıları büyük ticari sonuçlar, dolayısıyla tablo arketip skoru elverişsiz olsa bile nelerin mümkün olduğu konusunda bilgi veriyor.

| Oyun | Arketip (Ω) | Tahmini adet (orta) | Tahmini net gelir | C | E (M) | Early Access |
|---|---|---|---|---|---|---|
| Schedule I | Building (-0.50) | 10.11M | $99.01M | 0.311 | 274.6 | evet |
| Balatro | Turn-Based Strategy (-0.50) | 2.83M | $23.72M | 0.228 | 85.4 | hayır |
| Dwarf Fortress | Building (-0.50) | 652k | $10.95M | 0.269 | 34.3 | hayır |
| The Coffin of Andy and Leyley | Female Protagonist (-0.71) | 704k | $3.96M | 0.137 | 21.1 | evet |
| Fields of Mistria | Building (-0.50) | 945k | $7.40M | 0.319 | 20.0 | hayır |
| WEBFISHING | Character Customization (-0.37) | 1.85M | $6.47M | 0.277 | 19.8 | hayır |
| ZERO Sievert | Survival (-0.71) | 404k | $3.96M | 0.250 | 13.2 | hayır |
| Mon Bazou | Building (-0.50) | 405k | $4.53M | 0.306 | 12.7 | hayır |

**DELTARUNE olmadan seçim.** DELTARUNE listeden çıkarılsaydı Your Only Move Is HUSTLE listeye girerdi. Bu oyun seçimin en yüksek C değerine (0.307) sahip, geliştiricisinin saklanan veride bir başka başlığı var ve toplam tahmini net gelirin yarısından fazlasını oluşturuyor. Bu kontrol, özetteki toplamların tek bir oyuna ne kadar bağlı olduğunu göstermek için eklendi.

Karmaşıklık skoru kurulum boyutu, başarım sayısı ve geliştirici katalog büyüklüğü gibi metaverilerden oluşuyor. Bu oyunların bir kısmında
onları yapmanın eforunu olduğundan düşük gösteriyor olabilir. Örneğin Dwarf Fortress uzun soluklu bir proje ve Steam sürümü sonraki bir baskı.
Bu not pipeline verisinden değil, oyun hakkındaki genel bilgiden geliyor.

## 7. Sınırlılıklar

1. **Adet tahminleri.** Adetler, yorum sayısının tür kovası çarpanlarıyla çarpılmasıyla elde edilir (FORMULATION §2). Orada atıf yapılan kaynak, bu yöntemde oyunların yalnızca yaklaşık %43'ünün gerçek satışın ±%30'u içine düştüğünü bildiriyor. Net gelirde ayrıca indirim veya iade küçülmesi uygulanmıyor (δ = ρ = 0), bu yüzden gerçek eline geçen geliri büyük olasılıkla olduğundan yüksek gösteriyor.
2. **SteamSpy sahip bantları.** Bantlar kaba ve 2018 sonrası için güvenilirlikleri düşük (ARCHITECTURE.md, sınırlılık 1). Yalnızca makullük kontrolü olarak gösterildi.
3. **Karmaşıklık skoru.** C, mağaza metaverisine dayanan bir vekil ölçüdür ve geliştirme süresini ölçmez. Animal Well'in kurulum boyutu havuzun 1. yüzdeliğinde, bu da C'sini düşürüyor ve üretim eforunu yansıtması olası değil.
4. **Sonuca göre seçilmiş örneklem.** Tüm oyunlar SteamSpy'da en az 50,000 sahip bandında yer alıyor. Arketip talebi bu yüzden ticari olarak ayakta kalmaya koşullu ve bu run'dan bir başarısızlık oranı türetilemez.
5. **Arketip ataması.** Oyunlar, genel olmayan tag'ler üzerinden çoğunluk oyuyla bir arketipe atanır. Etiket oyunu değil, en çok birlikte görülen üç tag'i tanımlar. Bu seçimde de gevşek atamalar var: Void Stranger, FPS / Difficult / Violent arketipinin etiket tag'lerinden yalnızca Difficult'ı taşıyor ve SIGNALIS'in en çok oy alan tag'leri Survival Horror ve Psychological Horror olduğu halde Mystery tag'i üzerinden Mystery / Point & Click / Investigation arketipine atanmış. Arketip skorları bu oyunlar için bilgi taşımıyor olabilir.
6. **Küçük gruplar.** Seçimdeki arketipler pencerede 9 ile 24 oyun içeriyor ve en küçüğü (FPS / Difficult / Violent) 9 oyunla puanlama kuralının 5 oyunluk tabanına yakın. Küçük örneklemde tek bir oyun medyanı belirgin biçimde değiştirebilir.
7. **Parametreler ve sürüm.** Tüm satırlarda `parameters_version` `e5e095876f70`. Run'ın penceresi ve kümeleme eşiği önceki run'lardan sonra değiştirildi (todo.md madde 6 ve 7) ve bu analiz sürümü yeniden hesaplandı, bu yüzden Ω değerleri önceki run'larla veya önceki analiz sürümleriyle karşılaştırılabilir olmayabilir.
8. **Tek run.** Sonuç, 2026-10-03 tarihli tek bir taramayı anlatıyor. Sonraki bir tarama sıralamayı değiştirebilir.

## 8. Dosyalar

- `rapor.md` bu rapordur, `rapor_assets/` dokuz grafiği içerir.
- `scripts/top10_data.py` seçim kuralını uygular, `scripts/top10_figures.py` grafikleri çizer, `scripts/top10_notes.py` oyun yorumlarını tutar ve `scripts/build_top10_report.py` raporu birleştirir.
