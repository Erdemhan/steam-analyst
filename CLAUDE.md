# steam-analyst

> Genel kurallar (ajan hiyerarşisi, kodlama standartları, akademik kurallar, token bütçesi)
> `~/.claude/CLAUDE.md` içinde ve otomatik yükleniyor. Bu dosya **yalnızca bu projeye özgü**
> olanları içerir. Global'de zaten yazan hiçbir şeyi burada tekrar etme.

---

## Proje Özeti

Steam Analyst, Steam kataloğunu resmi/dokümante API'ler üzerinden tarayıp; solo veya
1-2 kişilik bir ekibin makul bir sürede (birkaç hafta–ay) geliştirebileceği düşük
karmaşıklıktaki oyun arketiplerinden (tür/tag/mekanik kombinasyonları) hangilerinin
Steam'de ticari olarak kanıtlanmış şekilde başarılı olduğunu tespit eden, tek makinede
çalışan, manuel tetiklenen bir analiz aracıdır. Her çalıştırma ("run") SQLite'a kalıcı
olarak kaydedilir; sonuçlar Streamlit tabanlı web arayüzünden hem anlık hem geçmişe
dönük olarak incelenebilir.

**Araştırma sorusu**: Hangi düşük-karmaşıklıklı oyun arketipleri Steam'de ticari olarak
başarılı olduğunu kanıtlamıştır, ve yüksek talep ile düşük rekabetin kesiştiği güncel
fırsat boşlukları nerededir?

---

## Bağlam Dosyaları

| Dosya | Rol |
|---|---|
| `.claude/context/FORMULATION.md` | Kanonik denklemler (Boxleiter tahmini, karmaşıklık skoru, fırsat skoru), semboller, parametre değerleri. **Kullanıcı-kilitli — şu an tüm sabitler `PROPOSED`, onay bekliyor.** |
| `.claude/context/ARCHITECTURE.md` | Mimari kararlar, modül yapısı, ADR günlüğü, veri modeli, bilinen sınırlılıklar. |
| `.claude/specs/*.module_spec.json` | Her modül için (`config`, `storage`, `acquisition`, `enrichment`, `analysis`, `reporting`) makine-okunur spec taslağı — `@module-planner`'ın girdisi. |
| `.claude/context/context.db` | SQLite görev/oturum durumu. Git'e girmez. |

Oturum başlangıcında `@context-manager` çalışır ve `context.db` yoksa oluşturur:

```bash
python3 ~/.claude/hooks/context_db.py init      # ilk kurulum
python3 ~/.claude/hooks/context_db.py summary   # durum özeti
```

---

## Bu Projeye Özgü Teknik Kısıtlar

- **Veri kaynakları**: yalnızca resmi/dokümante API'ler — Steam Web API `appdetails`,
  Steam Reviews API, SteamSpy toplu `all` uç noktası. Steam Store HTML, SteamDB,
  SteamCharts scraping **kesinlikle yasak** (ToS riski, bkz. ADR-003).
- **İki aşamalı toplama hunisi**: önce SteamSpy toplu verisiyle kaba filtre
  (~150k uygulama → birkaç bin adaya indirme), sonra sadece hayatta kalan alt küme
  için `appdetails`/reviews çağrısı (ADR-004). Bu sıralamayı bozan bir değişiklik
  API maliyetini iki kat büyüklük artırır.
- **Tek süreç, tek dosya**: tek Python süreci, tek SQLite dosyası
  (`data/analyses.db`), tek Streamlit arayüzü — ayrı backend/frontend yok (ADR-001,
  ADR-002). Zamanlayıcı/cron yok; run'lar manuel tetiklenir (ADR-006).
- **Aşama izolasyonu**: `acquisition`, `enrichment`, `analysis` modülleri birbirini
  import etmez, sadece veritabanı üzerinden iletişim kurar (ADR-009) — her aşama
  bağımsız olarak yeniden çalıştırılabilir olmalı.
- **Kullanıcı geliştirme profili**: solo/1-2 kişilik ekip, motor ve 2D/hafif-3D
  konusunda esnek. "Basitlik" eşikleri (`complexity_score`) buna göre geniş
  kalibre edilir, sadece 2D'ye kilitlenmez (ADR-008).
- **Ortam**: Windows geliştirme makinesi; yollar `pathlib.Path` ile dinamik
  çözümlenir (global kuralın heterojen ortam maddesiyle tutarlı, burada GPU/CUDA
  bağımlılığı yok).

---

## Run Kayıt Yeri

- **Ham veri + analiz sonuçları**: `data/analyses.db` (SQLite, git'e girmez, bkz.
  `.gitignore`). Her run bir `run_id` ile anahtarlanır; `raw_games`,
  `games_enriched`, `game_tags`, `analysis_results` tablolarında saklanır.
  Ham HTTP yanıtları değişmez (immutable) şekilde tutulur — bkz. ADR-005.
- **Görüntüleme**: ayrı bir figür/rapor üretim script'i yok. `reporting` modülü,
  saklanan veriden sunum modelini runtime'da üretir; Streamlit'in "Analysis Detail"
  sayfasında görüntülenir.
- **Tekrarlanabilirlik**: enrichment/analysis saf fonksiyonlardır, sadece saklanan
  ham veriden türetilir — formül veya eşik değişse bile ağa yeniden istek atmadan
  yeniden çalıştırılabilir.

---

## Açık Kararlar / Bilinen Sınırlılıklar

- `FORMULATION.md`'deki **tüm sayısal sabitler onay bekliyor** (henüz kilitlenmedi):
  Boxleiter tür-bazlı çarpan aralıkları ve kaynağı, karmaşıklık skoru ağırlıkları
  ve normalizasyon sınırları, kaba filtre bant aralığı, "basit" eşiği, fırsat skoru
  ağırlıkları (`w_D`, `w_K`, `w_Σ`) ve pencere genişliği `W`.
- Ücretsiz-oyun (F2P) gelir tahmininin nasıl ele alınacağı kararı bekliyor: adaydan
  tamamen çıkarma vs. gelir alanını "bilinmiyor" olarak işaretleyip tutma
  (ikincisi önerilir, bkz. `FORMULATION.md` §2).
- SteamSpy owner tahminleri 2018 sonrası düşük güvenilirlikte — kesin satış rakamı
  olarak asla sunulmamalı, sadece kaba sıralama sinyali (ARCHITECTURE.md, Bilinen
  Sınırlılık 1).
- Rate-limit varsayılanları resmi olarak dokümante edilmediği için muhafazakar
  tahminlere dayanıyor; ilk gerçek run sırasında gözlemsel olarak ayarlanması
  gerekebilir.
- Henüz hiç implementasyon kodu yok — bir sonraki adım `@module-planner`'ın
  `.claude/specs/*.module_spec.json` dosyalarını fonksiyon spec'lerine bölmesi.
