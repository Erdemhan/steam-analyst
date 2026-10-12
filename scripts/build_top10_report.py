"""Build rapor.md (top-10 game report, in Turkish) and its figures from the stored run.

Usage:
    python scripts/build_top10_report.py --db data/analyses.db

The report is derived from ``games_enriched``, ``tag_clusters``, ``opportunity_matrix`` and
``tag_trends`` of one stored run. Nothing is fetched from the network. The per-game
commentary lives in ``scripts/top10_notes.py`` and is the only hand-written part.
Requires matplotlib (not part of requirements.txt, report-only dependency).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import top10_data as t
import top10_figures as figs
from top10_notes import GAME_NOTES

ROOT = Path(__file__).resolve().parents[1]


def usd(x: float) -> str:
    if pd.isna(x):
        return "yok"
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"${x / 1e3:,.0f}k"
    return f"${x:,.2f}"


def units(x: float) -> str:
    if pd.isna(x):
        return "yok"
    return f"{x / 1e6:.2f}M" if x >= 1e6 else f"{x / 1e3:,.0f}k"


def size_txt(b: float) -> str:
    if pd.isna(b):
        return "yok"
    return f"{b / 1e9:.1f} GB" if b >= 1e9 else f"{b / 1e6:,.0f} MB"


def ordinal(x: float) -> str:
    return f"{max(1, int(round(x)))}."


def join_names(names: list[str]) -> str:
    if len(names) > 1:
        return ", ".join(names[:-1]) + " ve " + names[-1]
    return names[0] if names else "hiçbir oyun"


def short_label(label: str) -> str:
    return label.split(" / ")[0]


def band_position(mid: float, lo: float, hi: float) -> str:
    """Return where the Boxleiter mid estimate lies relative to the SteamSpy owner band."""
    if pd.isna(lo):
        return "yok"
    if mid < lo:
        return "altında"
    if mid > hi:
        return "üstünde"
    return "içinde"


def label_tags(d: t.ReportData, appid: int, label: str) -> str:
    tg = d.tags[d.tags["appid"] == appid].set_index("tag")["votes"]
    parts = []
    for name in label.split(" / "):
        parts.append(f"{name} ({int(tg[name])})" if name in tg.index else f"{name} (kayıtlı tag'ler arasında yok)")
    return ", ".join(parts)


def top_tags(d: t.ReportData, appid: int, n: int = 8) -> str:
    tg = d.tags[d.tags["appid"] == appid].sort_values("votes", ascending=False).head(n)
    return ", ".join(f"{a} ({int(b)})" for a, b in zip(tg["tag"], tg["votes"]))


def early_access_variant(d: t.ReportData) -> pd.DataFrame:
    p = d.pool
    p = p[(p["is_free"] == 0) & (p["review_positive_pct"] >= t.MIN_POSITIVE_SHARE)]
    p = p.sort_values("effort_adjusted_return", ascending=False)
    return p.groupby("cluster_id", sort=False).head(t.MAX_PER_ARCHETYPE).head(t.TOP_N)


def game_section(d: t.ReportData, r: pd.Series, simple_pool: pd.DataFrame) -> str:
    cat = json.loads(r["categories_json"]) if isinstance(r["categories_json"], str) else []
    modes = [m for m in ("Single-player", "Multi-player", "Co-op", "PvP", "Online PvP", "Online Co-op") if m in cat]
    imputed = json.loads(r["imputed_features_json"]) if isinstance(r["imputed_features_json"], str) else []
    c_pct = float((simple_pool["complexity_score"] <= r["complexity_score"]).mean()) * 100
    c_pool_pct = float((d.pool["complexity_score"] <= r["complexity_score"]).mean()) * 100
    band = band_position(r["estimated_sales_mid"], r["owners_lo"], r["owners_hi"])
    arche = d.matrix[d.matrix["cluster_id"] == r["cluster_id"]].iloc[0]
    n = GAME_NOTES[r["appid"]]
    ach = "yok" if pd.isna(r["achievement_count"]) else int(r["achievement_count"])
    lines = [
        f"### {int(r['rank'])}. {r['name']}",
        "",
        "| | | | |",
        "|---|---|---|---|",
        f"| Geliştirici / yayıncı | {r['developer']} / {r['publisher']} | Çıkış | {r['release_date']} (run'dan {r['age_months']:.0f} ay önce) |",
        f"| Arketip (Ω) | {short_label(r['label'])} ({r['opportunity_score']:+.2f}, {int(arche['n_games'])} oyun) | Liste fiyatı | ${r['price_usd']:.2f} |",
        f"| Yorum sayısı / olumlu oran | {int(r['review_count']):,} / %{r['review_positive_pct'] * 100:.1f} | Tahmini adet düşük / orta / yüksek | {units(r['estimated_sales_low'])} / {units(r['estimated_sales_mid'])} / {units(r['estimated_sales_high'])} |",
        f"| Tahmini net gelir | {usd(r['estimated_revenue_net_usd'])} | Çaba-ayarlı getiri E | {r['effort_adjusted_return'] / 1e6:,.1f}M |",
        f"| Karmaşıklık skoru C | {r['complexity_score']:.3f} ({len(simple_pool):,} basit oyun içinde {ordinal(c_pct)} yüzdelik, {len(d.pool)} oyunluk havuzda {ordinal(c_pool_pct)}) | SteamSpy sahip bandı | {r['steamspy_owners'] or 'yok'}, Boxleiter orta tahmini bandın **{band}** |",
        f"| Aylık ortalama adet | {r['sales_per_month']:,.0f} | Kurulum boyutu / asgari RAM | {size_txt(r['size_bytes'])} / {size_txt(r['ram_bytes'])} |",
        f"| Dil / başarım / DLC / platform sayısı | {int(r['language_count'])} / {ach} / {int(r['dlc_count'])} / {int(r['platform_count'])} | Oyuncu modları (Steam kategorileri) | {', '.join(modes) or 'yok'} |",
        "",
        f"En çok oy alan tag'ler: {top_tags(d, int(r['appid']))}.",
        "",
        f"Oyunun taşıdığı arketip etiket tag'leri: {label_tags(d, int(r['appid']), r['label'])}."
        + (f" Karmaşıklık skorunda tahmini (imputed) girdiler: {', '.join(imputed)}." if imputed else ""),
        "",
    ]
    lines += [f"- {x}" for x in n["observations"]]
    lines += ["", f"**Küçük bir ekip açısından okuma.** {n['reading']}", ""]
    return "\n".join(lines)


def build(db: Path, out_md: Path, assets: Path) -> None:
    d = t.load(db)
    f = figs.build_all(d, assets)
    top = d.top
    rel = lambda p: f"{assets.name}/{p.name}"  # noqa: E731
    simple_pool = d.games[d.games["complexity_score"] <= d.simple_threshold]

    arche_ids = list(dict.fromkeys(top["cluster_id"].astype(int)))
    am = d.matrix.set_index("cluster_id").loc[arche_ids]

    ea_variant = early_access_variant(d)
    ea_added = ea_variant[~ea_variant["appid"].isin(top["appid"])]
    ea_removed = top[~top["appid"].isin(ea_variant["appid"])]

    band_counts = top.apply(lambda r: band_position(r["estimated_sales_mid"], r["owners_lo"], r["owners_hi"]), axis=1).value_counts()
    self_pub = int((top["developer"] == top["publisher"]).sum())
    one_lang = int((top["language_count"] == 1).sum())

    overview = ["| # | Oyun | Arketip | Çıkış | Fiyat | Yorum (olumlu) | Tahmini adet (orta) | Tahmini net gelir | C | E (M) |",
                "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in top.iterrows():
        overview.append(
            f"| {int(r['rank'])} | {r['name']} | {short_label(r['label'])} | {r['release'].strftime('%Y-%m')} | ${r['price_usd']:.2f} | "
            f"{int(r['review_count']):,} (%{r['review_positive_pct'] * 100:.0f}) | {units(r['estimated_sales_mid'])} | "
            f"{usd(r['estimated_revenue_net_usd'])} | {r['complexity_score']:.3f} | {r['effort_adjusted_return'] / 1e6:,.1f} |")

    arche_rows = ["| Arketip | Oyun | D | K | Σ | Ω | Medyan tahmini adet | Medyan C | Tek oyunculu / çok oyunculu / co-op payı | Seçilen oyunlar |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
    for cid, r in am.iterrows():
        picked = ", ".join(top[top["cluster_id"] == cid]["name"])
        arche_rows.append(
            f"| {r['label']} | {int(r['n_games'])} | {r['demand_z']:+.2f} | {r['competition_z']:+.2f} | {r['simplicity_z']:+.2f} | "
            f"{r['opportunity_score']:+.2f} | {r['median_estimated_sales_mid']:,.0f} | {r['median_complexity']:.3f} | "
            f"%{r['singleplayer_share'] * 100:.0f} / %{r['multiplayer_share'] * 100:.0f} / %{r['coop_share'] * 100:.0f} | {picked} |")

    outside = ["| Oyun | Arketip (Ω) | Tahmini adet (orta) | Tahmini net gelir | C | E (M) | Early Access |", "|---|---|---|---|---|---|---|"]
    for _, r in d.outside_hits.iterrows():
        outside.append(
            f"| {r['name']} | {short_label(r['label'])} ({r['opportunity_score']:+.2f}) | {units(r['estimated_sales_mid'])} | "
            f"{usd(r['estimated_revenue_net_usd'])} | {r['complexity_score']:.3f} | {r['effort_adjusted_return'] / 1e6:,.1f} | {'evet' if r['is_early_access'] else 'hayır'} |")

    mp = am[am["multiplayer_share"] > 0.10]
    mp_names = [f"{short_label(l)} (%{s * 100:.0f})" for l, s in zip(mp["label"], mp["multiplayer_share"])]
    if mp_names:
        mp_text = "Çok oyunculu payı %10'un üzerinde olan arketipler yalnızca " + join_names(mp_names) + "."
    else:
        mp_text = "Hiçbir arketipte çok oyunculu payı %10'u aşmıyor."
    ea_prices = join_names([f"{n} (${p:.2f})" for n, p in zip(ea_added["name"], ea_added["price_usd"])])

    total_mid = top["estimated_sales_mid"].sum()
    total_rev = top["estimated_revenue_net_usd"].sum()
    pt = top.iloc[0]
    pt_share = pt["estimated_revenue_net_usd"] / total_rev * 100
    med_price = top["price_usd"].median()
    med_c = top["complexity_score"].median()
    pool_med_c = d.pool["complexity_score"].median()
    start, end = d.run["started_at"][:10], d.last_stage_finished[:10]
    top2 = am.sort_values("opportunity_score", ascending=False).head(2)
    top2_text = join_names([f"{short_label(l)} ({o:+.2f})" for l, o in zip(top2["label"], top2["opportunity_score"])])
    n_min, n_max = int(am["n_games"].min()), int(am["n_games"].max())
    smallest = am.loc[am["n_games"].idxmin(), "label"]
    first = top.iloc[0]
    without_first = d.eligible[d.eligible["appid"] != first["appid"]]
    without_first = without_first.groupby("cluster_id", sort=False).head(t.MAX_PER_ARCHETYPE).head(t.TOP_N)
    added_wo_first = without_first[~without_first["appid"].isin(top["appid"])]
    software_text = (f"Bu kümedeki {d.software_removed} oyun çıkarıldı (todo.md madde 9)." if d.software_removed
                     else "Bu run'ın arketip matrisinde yazılım benzeri bir küme kalmadı (todo.md madde 9).")

    md = f"""# Mevcut Analize Göre En Mantıklı 10 Oyun

Bu rapor, `{t.RUN_ID}` kimlikli kayıtlı run'dan ({d.run['notes']}) üretildi. Tarama {start} tarihinde başladı, enrichment ve analysis aşamaları en son {end} tarihinde tamamlandı.
Tüm sayılar saklanan veriden türetildi, yeni bir ağ isteği yapılmadı. Yeniden üretmek için
`python scripts/build_top10_report.py --db data/analyses.db` çalıştırılır.

**Veri sürümü.** Sonuçlar `parameters_version = {d.parameters_version}` ile saklanan analize aittir. Aynı run'ın enrichment ve analysis aşamaları {end} tarihinde yeniden çalıştırıldı.
Ana çalışma klasöründeki `config/parameters.toml` dosyası, o tarihte bir yazılım türü dışlama listesi (`enrichment.exclusions.software_genres`) ve `max_cluster_share = 0.15` ayarı içeriyordu.
Bu ayarların sonuçlara ayrı ayrı katkısı bu raporda ölçülmedi. Önceki bir analiz sürümüyle yapılacak karşılaştırmalarda sonuçlar aynı parametrelerle üretilmemiş olabilir.

## 1. Özet

On oyun, run'ın {d.funnel[1][1]:,} oyunluk basit alt kümesinden seçildi (karmaşıklık skoru C en düşük %40'ta).
Her biri son 48 ay içinde çıkmış, fırsat skoru Ω pozitif bir arketipe ait, ücretli, Early Access'ten çıkmış ve
olumlu yorum oranı en az %80. Sıralama FORMULATION §5'teki çaba-ayarlı getiri E'ye göre yapıldı ve arketip başına en fazla iki oyun alındı.

- Seçim {len(am)} arketipi kapsıyor: {', '.join(short_label(l) for l in am['label'])}. Seçimdeki arketipler arasında en yüksek Ω değerleri {top2_text}.
- On oyun birlikte yaklaşık {units(total_mid)} tahmini adet ve {usd(total_rev)} tahmini net gelire karşılık geliyor. Bu gelirin %{pt_share:.0f}'i tek bir oyundan ({pt['name']}) geliyor ve bu oyun olmadan toplam {usd(total_rev - pt['estimated_revenue_net_usd'])} olur. Toplamlar bu nedenle tek bir oyunun etkisinde.
- Seçimin medyan liste fiyatı ${med_price:.2f}, medyan C değeri {med_c:.3f}. Seçimin çekildiği {len(d.pool)} oyunluk havuzun medyan C değeri {pool_med_c:.3f}.
- On oyunun içinde {self_pub} oyun kendi yayıncısı (geliştirici ve yayıncı alanları aynı), {one_lang} oyun tek dil listeliyor. Bu durum, geniş yerelleştirmenin bu sonuçlar için bir ön koşul olmamış olabileceğini düşündürüyor.
- Yorum tabanlı adet tahmini {int(band_counts.get('içinde', 0))} oyunda SteamSpy sahip bandının içinde, {int(band_counts.get('üstünde', 0))} oyunda üstünde, {int(band_counts.get('altında', 0))} oyunda altında kalıyor. Tahminler sıralama sinyali olarak tutarlı görünüyor ancak satış rakamı olarak alıntılanmamalı (§7).
- Seçimin dayandığı arketipler küçük (her biri {n_min} ile {n_max} oyun arasında). Ω değerleri daha büyük bir örneklemle belirgin biçimde değişebilir, bu yüzden arketip düzeyindeki çıkarımlar oyun düzeyindeki gözlemlerden daha zayıf.

## 2. Veri ve Seçim Kuralı

Run'da {d.funnel[0][1]:,} zenginleştirilmiş oyun var. SteamSpy toplu listesi sahip sayısına göre sıralı ve burada kullanılan 10 katalog sayfası
50,000–100,000 sahip bandında bitiyor. Dolayısıyla run'daki her oyun en az bu kitle büyüklüğüne ulaşmış bir oyun ve bu,
talep skorlarının nasıl okunabileceğini etkiliyor (§7).

![Seçim hunisi]({rel(f['funnel'])})

Seçim kuralı yalnızca pipeline'ın zaten ürettiği nicelikleri kullanıyor.

1. **Basit alt küme.** C, run'ın 40. yüzdeliğinde veya altında ({d.simple_threshold:.3f}), FORMULATION §3a'da kilitlendiği gibi.
2. **Yakın tarihli.** {d.window_start.date()} veya sonrasında çıkmış (run başlangıcından 48 ay önce, FORMULATION §6'daki pencere W).
3. **Ω > 0 olan puanlanmış arketip.** Etiketi "Utilities / Software" ile başlayan yazılım benzeri küme varsa çıkarılır. {software_text}
4. **Ücretli, tamamlanmış, iyi karşılanmış.** Ücretsiz oyunların gelir tahmini yok, Early Access oyunlar bitmemiş ve %80'in altındaki olumlu yorum oranı ürün kalitesi için zayıf kanıt sayıldı.
5. **Sıralama.** Çaba-ayarlı getiri E = R_net / (C + 0.05). Tek bir arketip listeyi doldurmasın diye arketip başına en fazla {t.MAX_PER_ARCHETYPE} oyun.

Havuzun Ω > 0 arketiplerle sınırlanması projenin araştırma sorusunu izliyor: talebin yüksek, rekabetin düşük olduğu yerler nerede?
Diğer arketiplerin en güçlü oyunları kaybolmasın diye §6'da ayrıca listelendi.

## 3. Arketip Bağlamı

![Arketip haritası]({rel(f['map'])})

{chr(10).join(arche_rows)}

D, K ve Σ sırasıyla medyan tahmini adedin, penceredeki çıkış sayısının ve bir eksi medyan C'nin z-skorlarıdır. Ω = 0.40·D − 0.30·K + 0.30·Σ (FORMULATION §6).

![Oyuncu modu payları]({rel(f['modes'])})

Bu seçimdeki arketipler ağırlıklı olarak tek oyunculu. {mp_text}

![Arketip satış trendi]({rel(f['trends'])})

Her nokta en fazla altı oyunun medyanıdır, dolayısıyla çizgiler yalnızca betimleyicidir. FORMULATION §6, bu eğimlere anlamlılık iddiası bağlanmadığını belirtiyor.

## 4. On Oyuna Genel Bakış

{chr(10).join(overview)}

![Karmaşıklık ve gelir]({rel(f['cx_rev'])})

![Yüzdelik profili]({rel(f['heat'])})

Yüzdelik sütunları her oyunu {len(d.pool)} oyunluk havuzla karşılaştırır. Karmaşıklık sütununda yüksek yüzdelik daha karmaşık bir oyun anlamına gelir.

![Fiyat ve hacim]({rel(f['price'])})

![Aylık ortalama adet]({rel(f['per_month'])})

Aylık ortalama, yaşam boyu tahmini adedi çıkıştan beri geçen aya böler. Satışların çıkışta yoğunlaşan olağan eğrisini gizler, bu yüzden eski oyunlar güncel hızlarından daha yavaş görünür.

![Satış tahmini ve sahip bandı]({rel(f['ranges'])})

## 5. Oyun Oyun Analiz

{chr(10).join(game_section(d, r, simple_pool) for _, r in top.iterrows())}

## 6. Duyarlılık ve Seçim Dışı Kalan Oyunlar

**Early Access.** Early Access oyunlara izin verilseydi {join_names(list(ea_added['name']))} listeye girer,
{join_names(list(ea_removed['name']))} listeden çıkardı. Girecek Early Access oyunların fiyatları {ea_prices or 'yok'} ve bunlar mevcut seçimin medyan fiyatının üzerinde.

**Ω ≤ 0 arketiplerde yüksek E'li oyunlar.** Bu oyunlar, arketipleri run'ın kendi ölçüsüne göre kalabalık veya düşük talepli olduğu için seçilmedi.
Bazıları büyük ticari sonuçlar, dolayısıyla tablo arketip skoru elverişsiz olsa bile nelerin mümkün olduğu konusunda bilgi veriyor.

{chr(10).join(outside)}

**{first['name']} olmadan seçim.** {first['name']} listeden çıkarılsaydı {join_names(list(added_wo_first['name']))} listeye girerdi. Bu oyun seçimin en yüksek C değerine ({first['complexity_score']:.3f}) sahip, geliştiricisinin saklanan veride bir başka başlığı var ve toplam tahmini net gelirin yarısından fazlasını oluşturuyor. Bu kontrol, özetteki toplamların tek bir oyuna ne kadar bağlı olduğunu göstermek için eklendi.

Karmaşıklık skoru kurulum boyutu, başarım sayısı ve geliştirici katalog büyüklüğü gibi metaverilerden oluşuyor. Bu oyunların bir kısmında
onları yapmanın eforunu olduğundan düşük gösteriyor olabilir. Örneğin Dwarf Fortress uzun soluklu bir proje ve Steam sürümü sonraki bir baskı.
Bu not pipeline verisinden değil, oyun hakkındaki genel bilgiden geliyor.

## 7. Sınırlılıklar

1. **Adet tahminleri.** Adetler, yorum sayısının tür kovası çarpanlarıyla çarpılmasıyla elde edilir (FORMULATION §2). Orada atıf yapılan kaynak, bu yöntemde oyunların yalnızca yaklaşık %43'ünün gerçek satışın ±%30'u içine düştüğünü bildiriyor. Net gelirde ayrıca indirim veya iade küçülmesi uygulanmıyor (δ = ρ = 0), bu yüzden gerçek eline geçen geliri büyük olasılıkla olduğundan yüksek gösteriyor.
2. **SteamSpy sahip bantları.** Bantlar kaba ve 2018 sonrası için güvenilirlikleri düşük (ARCHITECTURE.md, sınırlılık 1). Yalnızca makullük kontrolü olarak gösterildi.
3. **Karmaşıklık skoru.** C, mağaza metaverisine dayanan bir vekil ölçüdür ve geliştirme süresini ölçmez. Animal Well'in kurulum boyutu havuzun 1. yüzdeliğinde, bu da C'sini düşürüyor ve üretim eforunu yansıtması olası değil.
4. **Sonuca göre seçilmiş örneklem.** Tüm oyunlar SteamSpy'da en az 50,000 sahip bandında yer alıyor. Arketip talebi bu yüzden ticari olarak ayakta kalmaya koşullu ve bu run'dan bir başarısızlık oranı türetilemez.
5. **Arketip ataması.** Oyunlar, genel olmayan tag'ler üzerinden çoğunluk oyuyla bir arketipe atanır. Etiket oyunu değil, en çok birlikte görülen üç tag'i tanımlar. Bu seçimde de gevşek atamalar var: Void Stranger, FPS / Difficult / Violent arketipinin etiket tag'lerinden yalnızca Difficult'ı taşıyor ve SIGNALIS'in en çok oy alan tag'leri Survival Horror ve Psychological Horror olduğu halde Mystery tag'i üzerinden Mystery / Point & Click / Investigation arketipine atanmış. Arketip skorları bu oyunlar için bilgi taşımıyor olabilir.
6. **Küçük gruplar.** Seçimdeki arketipler pencerede {n_min} ile {n_max} oyun içeriyor ve en küçüğü ({smallest}) {n_min} oyunla puanlama kuralının 5 oyunluk tabanına yakın. Küçük örneklemde tek bir oyun medyanı belirgin biçimde değiştirebilir.
7. **Parametreler ve sürüm.** Tüm satırlarda `parameters_version` `{d.parameters_version}`. Run'ın penceresi ve kümeleme eşiği önceki run'lardan sonra değiştirildi (todo.md madde 6 ve 7) ve bu analiz sürümü yeniden hesaplandı, bu yüzden Ω değerleri önceki run'larla veya önceki analiz sürümleriyle karşılaştırılabilir olmayabilir.
8. **Tek run.** Sonuç, {start} tarihli tek bir taramayı anlatıyor. Sonraki bir tarama sıralamayı değiştirebilir.

## 8. Dosyalar

- `rapor.md` bu rapordur, `rapor_assets/` dokuz grafiği içerir.
- `scripts/top10_data.py` seçim kuralını uygular, `scripts/top10_figures.py` grafikleri çizer, `scripts/top10_notes.py` oyun yorumlarını tutar ve `scripts/build_top10_report.py` raporu birleştirir.
"""
    out_md.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "analyses.db")
    ap.add_argument("--out", type=Path, default=ROOT / "rapor.md")
    ap.add_argument("--assets", type=Path, default=ROOT / "rapor_assets")
    a = ap.parse_args()
    build(a.db, a.out, a.assets)
    print(f"wrote {a.out}")
