"""Info page: explains how the analysis works, its current parameters and open items.

Display-only. Parameter values are read from config/parameters.toml and the
FORMULATION.md record is never modified from here. All user-visible strings are
Turkish by explicit user request.
"""

import sqlite3
from typing import Any

import pandas as pd
import streamlit as st

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

from steam_analyst.config import Settings

_FLOW_DOT = """
digraph G {
  rankdir=TB;
  node [shape=box, style="rounded,filled", fillcolor="#383a40", fontcolor="#e3e5e8",
        color="#5b9bd5", fontname="Helvetica"];
  edge [color="#9aa0a6", fontcolor="#e3e5e8", fontname="Helvetica"];
  bgcolor="transparent";

  start [label="Yeni analiz başlat\\n(manuel, form)", shape=oval];
  spy [label="1. Katalog taraması\\nSteamSpy toplu veri (~150 bin uygulama)"];
  coarse [label="2. Kaba filtre\\nmin. 25 yorum, 2020 ve sonrası,\\nyayıncı kara listesi dışı"];
  cand [label="Adaylar (birkaç bin oyun)", shape=note];
  detail [label="3. Ayrıntı toplama (yalnızca adaylar)\\nSteam appdetails + yorum API'si"];
  db1 [label="Ham veri (SQLite, değişmez)", shape=cylinder];
  enr [label="4. Zenginleştirme\\nBoxleiter satış tahmini, net gelir,\\nkarmaşıklık skoru, etkin getiri"];
  simple [label="5. Basitlik filtresi\\nkarmaşıklığı en düşük %40"];
  clus [label="6. Arketip kümeleme\\nEtiket benzerliği (Jaccard), ortalama bağlantı"];
  score [label="7. Arketip skorlama\\nTalep, rekabet, basitlik (z) -> fırsat skoru"];
  trend [label="8. Eğilimler\\n4 aylık 6 dilim, OLS eğimi"];
  rep [label="9. Raporlama\\nFırsat matrisi, etiket özeti,\\nvaka çalışmaları, uyarılar"];
  ui [label="Analiz ayrıntısı sayfası", shape=oval];

  start -> spy -> coarse -> cand -> detail -> db1 -> enr -> simple -> clus -> score -> rep -> ui;
  clus -> trend -> rep;
}
"""

_STEPS = [
    (
        "1. Katalog taraması",
        "SteamSpy'ın toplu 'all' uç noktasından katalogdaki uygulamalar sayfa sayfa "
        "çekilir. Form'daki 'Katalog sayfa sınırı' kaç sayfa çekileceğini belirler "
        "(her sayfa yaklaşık 1000 uygulama). Sayfa sayısı azsa aday sayısı da az olur ve "
        "sonuçlar boş ya da güvensiz çıkabilir.",
    ),
    (
        "2. Kaba filtre",
        "Yüz binlerce uygulama içinden yalnızca anlamlı adaylar ayrıştırılır: en az 25 "
        "yorum, 1 Ocak 2020 ve sonrası çıkış, büyük yayıncı kara listesinde olmayanlar. "
        "Ücretsiz oyunlar da dahildir ancak geliri bilinmiyor olarak işaretlenir. Bu "
        "sıra bilerek böyledir. Ayrıntılı API çağrıları yalnızca hayatta kalanlara "
        "yapılır ve istek maliyeti bir büyüklük mertebesi azalır.",
    ),
    (
        "3. Ayrıntı toplama",
        "Adaylar için Steam'in resmi 'appdetails' ve yorum API'leri çağrılır. Ham "
        "yanıtlar değiştirilmeden saklanır. İstek hızı ve toplam istek bütçesi ile "
        "sınırlıdır. Steam mağaza sayfası, SteamDB veya SteamCharts kazıması "
        "kullanılmaz.",
    ),
    (
        "4. Zenginleştirme",
        "Her oyun için (a) Boxleiter yöntemiyle tahmini satış: yorum sayısı x tür "
        "çarpanı, alt-orta-üst olmak üzere üç değer; (b) tahmini net gelir: satış x "
        "fiyat x (1 - %30 mağaza payı); (c) 0 ile 1 arasında karmaşıklık skoru "
        "(kurulum boyutu, erken erişim süresi, geliştiricinin oyun sayısı, başarım ve "
        "DLC sayısı, basitlik/karmaşıklık etiketleri, platform ve dil sayısı); "
        "(d) etkin getiri: net gelir / (karmaşıklık + 0,05).",
    ),
    (
        "5. Basitlik filtresi",
        "Adaylar içinde karmaşıklık skoru en düşük %40'lık dilimdeki oyunlar 'basit' "
        "kabul edilir. Sonraki adımlar yalnızca bu alt kümeyle çalışır.",
    ),
    (
        "6. Arketip kümeleme",
        "Oyunlar, etiket kümelerinin Jaccard mesafesine göre ortalama bağlantılı "
        "hiyerarşik kümelemeyle gruplanır. Her küme bir 'arketip'tir. Tür etiketine "
        "sabitlenmez, tamamen etiket birlikteliğinden doğar. En az 5 oyunu olmayan "
        "arketip skorlanmaz.",
    ),
    (
        "7. Arketip skorlama",
        "Her arketip için: talep = son 48 ayda çıkan oyunların medyan tahmini satışı; "
        "rekabet = aynı pencerede çıkan oyun sayısı (katalog büyümesine göre "
        "düzeltilmiş); basitlik = 1 - medyan karmaşıklık. Üçü de arketipler arasında "
        "z-skoruna çevrilir. Fırsat skoru = 0,40 x talep - 0,30 x rekabet + "
        "0,30 x basitlik.",
    ),
    (
        "8. Eğilimler",
        "Son 48 aylık pencere 4'er aylık 12 dilime bölünür. Her dilimde arketipin "
        "medyan tahmini satışı hesaplanır ve dilim numarasına karşı doğrusal regresyonla "
        "bir eğim üretilir. Betimleyicidir, anlamlılık testi içermez.",
    ),
    (
        "9. Raporlama ve vaka çalışmaları",
        "Saklanan veriden fırsat matrisi, etiket özeti, eğilimler ve vaka çalışmaları "
        "çalışma anında üretilir. Vaka çalışmaları etkin getiriye göre seçilir "
        "(en fazla 15 oyun, arketip başına 2, geliştirici başına 1). Her yüzeyde "
        "yorumlama uyarıları gösterilir.",
    ),
]

_PARAM_TR = {
    "acquisition.coarse_filter.min_review_count": "Kaba filtre: asgari yorum sayısı",
    "acquisition.coarse_filter.earliest_release_date": "Kaba filtre: en erken çıkış tarihi",
    "acquisition.coarse_filter.include_free_to_play": "Kaba filtre: ücretsiz oyunlar dahil mi",
    "acquisition.coarse_filter.publisher_blocklist": "Kaba filtre: dışlanan büyük yayıncılar",
    "acquisition.steamspy_page_delay_seconds": "SteamSpy sayfa arası bekleme (sn)",
    "acquisition.steam_requests_per_minute": "Steam istek hızı (dakikada)",
    "acquisition.max_retries": "En fazla yeniden deneme",
    "acquisition.backoff_base_seconds": "Geri çekilme başlangıcı (sn)",
    "acquisition.backoff_max_seconds": "Geri çekilme üst sınırı (sn)",
    "acquisition.request_budget": "Toplam istek bütçesi",
    "enrichment.boxleiter_multipliers.niche": "Boxleiter çarpanı: niş [alt, orta, üst]",
    "enrichment.boxleiter_multipliers.mainstream": "Boxleiter çarpanı: ana akım [alt, orta, üst]",
    "enrichment.boxleiter_multipliers.broad_audience": "Boxleiter çarpanı: geniş kitle [alt, orta, üst]",
    "enrichment.revenue.storefront_cut": "Mağaza komisyonu",
    "enrichment.revenue.discount_factor": "İndirim düzeltmesi",
    "enrichment.revenue.refund_regional_factor": "İade/bölgesel fiyat düzeltmesi",
    "enrichment.complexity_weights.size_bytes": "Karmaşıklık ağırlığı: kurulum boyutu",
    "enrichment.complexity_weights.ram_bytes": "Karmaşıklık ağırlığı: RAM gereksinimi",
    "enrichment.complexity_weights.early_access_days": "Karmaşıklık ağırlığı: erken erişim süresi",
    "enrichment.complexity_weights.dev_title_count": "Karmaşıklık ağırlığı: geliştiricinin oyun sayısı",
    "enrichment.complexity_weights.simplicity_tag_score": "Karmaşıklık ağırlığı: basitlik etiketleri",
    "enrichment.complexity_weights.complexity_tag_score": "Karmaşıklık ağırlığı: karmaşıklık etiketleri",
    "enrichment.complexity_weights.achievement_count": "Karmaşıklık ağırlığı: başarım sayısı",
    "enrichment.complexity_weights.dlc_count": "Karmaşıklık ağırlığı: DLC sayısı",
    "enrichment.complexity_weights.platform_count": "Karmaşıklık ağırlığı: platform sayısı",
    "enrichment.complexity_weights.language_count": "Karmaşıklık ağırlığı: dil sayısı",
    "enrichment.complexity_tags.simplicity_tags": "Basitlik etiketleri",
    "enrichment.complexity_tags.complexity_tags": "Karmaşıklık etiketleri",
    "enrichment.effort.epsilon": "Etkin getiri paydası sabiti (epsilon)",
    "enrichment.tag_extraction.max_per_game": "Oyun başına en fazla etiket",
    "enrichment.tag_extraction.min_votes": "Etiket için asgari oy",
    "analysis.simplicity_percentile": "Basitlik eşiği (en düşük karmaşıklık yüzdeliği)",
    "analysis.clustering_linkage": "Kümeleme bağlantı yöntemi",
    "analysis.trailing_window_months": "Analiz penceresi (ay)",
    "analysis.min_cluster_size": "Asgari arketip büyüklüğü (oyun)",
    "analysis.min_tag_votes": "Analizde asgari etiket oyu",
    "analysis.max_tags_per_game": "Analizde oyun başına en fazla etiket",
    "analysis.generic_tag_max_share": "Kümelemeden çıkarılan genel etiket eşiği (oyunların payı)",
    "analysis.tag_distance_threshold": "Kümeleme mesafe eşiği",
    "analysis.opportunity_weights.demand": "Fırsat ağırlığı: talep",
    "analysis.opportunity_weights.competition": "Fırsat ağırlığı: rekabet",
    "analysis.opportunity_weights.simplicity": "Fırsat ağırlığı: basitlik",
}

_OPEN_ITEMS = [
    (
        "Karmaşıklık sınırları küçük bir örneklemden donduruldu, skorlanabilen arketip sayısı az",
        "Normalizasyon sınırları, en çok sahibi olan 1000 uygulamanın 2020 sonrası "
        "çıkan 203 oyunluk alt kümesinden türetildi. Örneklem popüler oyunlara kaydığı "
        "için sınırlar tüm adaylara göre yukarı kayık olabilir. Kümeleme mesafe eşiği "
        "3000 uygulamalık bir taramanın 285 oyunluk basit alt kümesinden donduruldu. "
        "Bu alt kümedeki oyunların yalnızca 108'i son 48 ayda çıktı ve arketip başına en az "
        "5 oyun şartını 10 arketip sağlayabildi.",
        "Daha geniş bir taramadan sonra sınırların ve eşiğin yeniden türetilmesi "
        "FORMULATION.md kararı gerektirir (kullanıcı onayı şart).",
    ),
    (
        "Erken erişim süresi hiçbir oyun için alınamıyor",
        "Erken erişimde geçirilen gün sayısı belgelenmiş API'lerde yok. Erken erişim "
        "durumu türlerden okunuyor, ancak süre bilinmediği için bu özellik (ağırlık 0,05) "
        "herkes için sabit 0,5 değerinde kalıyor. Kurulum boyutu ve RAM ise "
        "sistem gereksinimi metninden okunuyor (örneklemde sırasıyla yaklaşık %97 ve %98).",
        "Erken erişim süresi için başka bir veri kaynağı ya da ağırlık revizyonu "
        "gerekiyor (FORMULATION.md kararı).",
    ),
    (
        "Büyük (AAA) yapımlar kaba filtreden geçebiliyor",
        "Kaba filtrenin yorum sayısı üst sınırı yok ve yayıncı kara listesi kapsamlı "
        "olamaz. Liste genişletildi ancak listede olmayan yayıncıların büyük yapımları "
        "aday havuzuna girebilir. Bu yüzden oyun grupları, talep, rekabet ve eğilim "
        "hesapları yalnızca karmaşıklık skoru en düşük %40'lık 'basit sayılan' dilim "
        "üzerinden yapılıyor. Sınırlar dondurulduğu için büyük yapımların karmaşıklık "
        "skoru yüksek çıkıyor ve bu dilime girmiyorlar. Kara liste değişikliği yalnızca "
        "yeni bir katalog taramasında etkili olur.",
        "Yorum sayısı üst sınırı eklenmesi FORMULATION.md §0 kararı gerektiriyor.",
    ),
    (
        "Ücretsiz oyunların gelir tahmini",
        "Şu an gelir bilinmiyor olarak işaretleniyor ve vaka çalışmalarından "
        "çıkarılıyor. Adaydan tamamen çıkarma seçeneği karara bağlanmadı.",
        "FORMULATION.md §2'de F2P kararı netleştirilmeli.",
    ),
    (
        "Tüm sayısal sabitler 'önerilen' durumda",
        "Boxleiter çarpan aralıkları, karmaşıklık ağırlıkları, basitlik eşiği, fırsat "
        "ağırlıkları ve pencere genişliği henüz literatürle doğrulanmış kesin değerler "
        "değil. Boxleiter sapması (yaklaşık %43'ü ±%30 içinde) 2018 sonrası için "
        "düşük güvenilirliktedir.",
        "Kaynakların gözden geçirilip değerlerin kullanıcı tarafından kilitlenmesi "
        "gerekiyor.",
    ),
    (
        "Basitlik etiketleri listesi tutarsız olabilir",
        "'Singleplayer' basitlik etiketi sayılırken 'Multiplayer' karmaşıklık etiketi "
        "sayılıyor. Tek oyunculu oyunlar çoğunluk olduğu için bu etiketin ayırt "
        "ediciliği düşük olabilir.",
        "Etiket listesi gözden geçirilmeli.",
    ),
    (
        "Etiket eğilimi raporu ile analiz çıktısı şema uyumsuzluğu",
        "Rapor katmanı 'tag, period, n_games, median_review_positive_pct' sütunlarını "
        "bekliyor, analiz ise dilim bazlı 'cluster_id, sub_window_*, slope' çıktısı "
        "üretiyor. Arayüz şu an yalnızca dolu sütunları gösteriyor.",
        "Kod düzeltmesi, FORMULATION değişikliği gerektirmez.",
    ),
    (
        "Eski çalıştırmalarda hatalı olumlu yorum oranı",
        "Düzeltme öncesi çalıştırılan analizlerde olumlu oran yanlış (ör. %8) "
        "saklanmış olabilir. Zenginleştirme adımı yeniden çalıştırılınca düzelir.",
        "Kod düzeltmesi yapıldı, eski çalıştırmalar için yeniden çalıştırma gerekiyor.",
    ),
    (
        "SteamSpy sahip sayıları kullanılmıyor",
        "Son çalıştırmada sahip tahmini alanları tüm oyunlarda boş. Satış tahmini yalnızca "
        "yorum sayısına dayanıyor.",
        "Veri kaynağı alanlarının eşlemesi gözden geçirilmeli.",
    ),
]


def _load_parameters(settings: Settings) -> dict[str, Any]:
    with open(settings.parameters_path, "rb") as handle:
        return tomllib.load(handle)


def _flatten(node: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value and path != "enrichment.genre_bucket_map":
            rows.extend(_flatten(value, path))
        else:
            rows.append((path, value))
    return rows


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "evet" if value else "hayır"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def render_info_page(conn: sqlite3.Connection, settings: Settings) -> None:
    """Render the info page.

    Args:
        conn: Unused; accepted for signature consistency with the other pages.
        settings: For settings.parameters_path.
    """
    st.header("Bilgi")
    st.write(
        "Bu sayfa analizin adım adım nasıl çalıştığını, şu an kullanılan parametreleri "
        "ve henüz kesinleşmemiş noktaları gösterir. Sayfa yalnızca bilgi amaçlıdır, "
        "buradan hiçbir değer değiştirilemez."
    )

    st.subheader("Amaç")
    st.write(
        "Steam'de, tek kişi ya da 1-2 kişilik bir ekibin birkaç hafta ile birkaç ay "
        "içinde yapabileceği kadar basit oyun arketiplerinden hangilerinin ticari "
        "olarak başarılı olduğunu ve talebin yüksek, rekabetin düşük olduğu güncel "
        "boşlukların nerede olduğunu bulmak."
    )

    st.subheader("Akış diyagramı")
    st.graphviz_chart(_FLOW_DOT)

    st.subheader("Adım adım analiz")
    for title, body in _STEPS:
        with st.expander(title):
            st.write(body)

    st.subheader("Sonuçlar nasıl okunur")
    st.markdown(
        "\n".join(
            [
                "- **Fırsat skoru** göreli bir sıralama ölçüsüdür, parasal bir karşılığı yoktur.",
                "- **Tahmini satış** yorum sayısından çıkarılan kaba bir değerdir. Kesin satış rakamı olarak okunmamalıdır.",
                "- **Karmaşıklık skoru** emeği değil, kapsamı yaklaşık olarak gösterir.",
                "- **Sonuçlar ilişkisel ve betimleyicidir.** Bir arketipin yüksek skoru, orada başarılı olunacağını garanti etmez.",
                "- **Küçük taramalarda** arketipler oluşmayabilir ve tablolar boş kalabilir.",
            ]
        )
    )

    st.subheader("Mevcut parametreler")
    try:
        params = _load_parameters(settings)
    except Exception as e:
        st.warning(f"Parametre dosyası okunamadı: {e}")
        params = {}

    if params:
        st.caption(
            "Değerler config/parameters.toml dosyasından okunur. Bu dosya "
            "FORMULATION.md kaydının makine tarafından okunabilir yansımasıdır. "
            "Değerleri değiştirmek için önce FORMULATION.md değişikliği onaylanmalıdır."
        )
        rows = _flatten(params)
        sections = {
            "Toplama": "acquisition.",
            "Zenginleştirme": "enrichment.",
            "Analiz": "analysis.",
        }
        tabs = st.tabs(list(sections))
        for tab, prefix in zip(tabs, sections.values()):
            with tab:
                frame = pd.DataFrame(
                    [
                        {
                            "Parametre": _PARAM_TR.get(path, path),
                            "Değer": _format_value(value),
                            "Anahtar": path,
                        }
                        for path, value in rows
                        if path.startswith(prefix)
                    ]
                )
                st.dataframe(frame, hide_index=True)
        unset = [
            "analysis.tag_distance_threshold",
            "enrichment.complexity_bounds",
        ]
        present = {path for path, _ in rows}
        missing = [key for key in unset if not any(p.startswith(key) for p in present)]
        if missing:
            st.info(
                "Şu parametreler dosyada tanımlı değil (henüz dondurulmadı): "
                + ", ".join(_PARAM_TR.get(k, k) for k in missing)
                + "."
            )

    st.subheader("Eksik ve güncellenmesi gereken noktalar")
    st.caption(
        "Yalnızca bilgilendirme amaçlıdır. FORMULATION.md kullanıcı tarafından kilitlidir "
        "ve burada ya da başka bir yerde onay olmadan değiştirilmez."
    )
    for title, detail, action in _OPEN_ITEMS:
        with st.expander(title):
            st.write(detail)
            st.markdown(f"**Gereken:** {action}")
