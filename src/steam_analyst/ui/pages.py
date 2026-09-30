"""Streamlit page renderers for the Steam Analyst UI.

This module contains the five page-rendering functions that compose the
three-page navigation: Run New Analysis, Past Analyses, and Analysis Detail.
Each function is called by the three-page navigation in main() and receives
either a connection opened by the caller (main's short-lived context) or
opens its own connection (render_progress_panel as a fragment).

Key principles:
- No database connection is cached or reused across reruns (ADR-017).
- No SQL, HTTP, or computation happens here; all logic is in reporting/orchestration.
- Session state is limited to SESSION_KEYS only: active_run_id, last_event_id, event_log.
- The form exposes only PipelineConfig fields; FORMULATION.md-governed values
  are never editable from the UI.
- Every surface showing a revenue or complexity figure also renders the caveat panel.
"""

import sqlite3
from pathlib import Path
from typing import Sequence

import pandas as pd
import streamlit as st

from steam_analyst.config import Settings
from steam_analyst import orchestration, reporting, storage
from .session import SESSION_KEYS

_NAV_PAGES: dict[str, st.Page] = {}


def register_nav_pages(pages: dict[str, st.Page]) -> None:
    """Store the st.Page objects built by the navigation so pages can switch to each other."""
    _NAV_PAGES.clear()
    _NAV_PAGES.update(pages)


_STATUS_TR = {
    "pending": "bekliyor",
    "running": "çalışıyor",
    "succeeded": "tamamlandı",
    "failed": "başarısız",
    "cancelled": "iptal edildi",
}

_STAGE_TR = {
    "acquisition": "Veri toplama",
    "enrichment": "Zenginleştirme",
    "analysis": "Analiz",
}

_COLUMN_TR = {
    "Cluster ID": "Küme no",
    "Archetype": "Arketip",
    "N": "Oyun sayısı",
    "Demand (z)": "Talep (z)",
    "Competition (z)": "Rekabet (z)",
    "Simplicity (z)": "Basitlik (z)",
    "Opportunity Score": "Fırsat skoru",
    "Est. Sales (band mid)": "Tahmini satış (orta)",
    "Complexity": "Karmaşıklık",
    "Releases in Window": "Penceredeki çıkışlar",
    "Tag": "Etiket",
    "Positive %": "Olumlu oran",
    "Price ($)": "Fiyat ($)",
    "cluster_id": "Küme no",
    "sub_window_index": "Alt pencere no",
    "sub_window_start": "Alt pencere başı",
    "sub_window_end": "Alt pencere sonu",
    "n_games": "Oyun sayısı",
    "median_estimated_sales_mid": "Tahmini satış (orta)",
    "slope": "Eğim",
    "slope_n_subwindows": "Eğimde alt pencere sayısı",
    "tag": "Etiket",
    "period": "Dönem",
    "median_review_positive_pct": "Olumlu oran",
}

_COLUMN_HELP_TR = {
    "Küme no": (
        "Analizin oluşturduğu arketipin (benzer etiketli oyun kümesi) numarası. "
        "Yalnızca tanımlayıcıdır, sıralama anlamı taşımaz."
    ),
    "Arketip": (
        "Kümeyi temsil eden otomatik ad. Steam türü değildir, kümedeki oyunların "
        "ortak etiket kombinasyonundan türetilir."
    ),
    "Oyun sayısı": (
        "Bu arketipte (ya da etiketle) analize giren oyun sayısı. Sayı küçükse değerler "
        "tek bir oyunun etkisiyle değişebilir. Bir arketipin skorlanması için en az "
        "5 oyun gerekir."
    ),
    "Talep (z)": (
        "Talep göstergesi. Arketipte son 24 ayda çıkan oyunların tahmini satışının "
        "medyanı, tüm arketipler arasında z-skoruna çevrilir. 0 ortalamadır, +1 "
        "ortalamanın bir standart sapma üstüdür. Yüksek değer, daha yüksek talep "
        "anlamına gelir."
    ),
    "Rekabet (z)": (
        "Rekabet göstergesi. Arketipte son 24 ayda çıkan oyun sayısı (katalog "
        "büyümesine göre düzeltilmiş), tüm arketipler arasında z-skoruna çevrilir. "
        "Yüksek değer, daha kalabalık bir pazar demektir. Fırsat skorundan "
        "çıkarılır."
    ),
    "Basitlik (z)": (
        "Basitlik göstergesi. 1 eksi arketipin medyan karmaşıklık skorunun z-skoru. "
        "Yüksek değer, arketipteki oyunların küçük kapsamlı (yapımı daha kolay) "
        "olduğunu gösterir."
    ),
    "Fırsat skoru": (
        "0,40 x Talep - 0,30 x Rekabet + 0,30 x Basitlik. Yüksek skor, talebi yüksek, "
        "rekabeti düşük ve yapımı basit arketip demektir. Skorun birimi ve parasal "
        "karşılığı yoktur, yalnızca arketipleri birbiriyle sıralamak için kullanılır."
    ),
    "Tahmini satış (orta)": (
        "Oyunların tahmini satış orta değerinin medyanı. Boxleiter yöntemiyle, yorum "
        "sayısı x tür çarpanı olarak hesaplanır. Kesin satış rakamı değil, kaba bir "
        "sıralama sinyalidir. Gerçek satışın yaklaşık %43'ü ±%30 içinde tahmin edilir."
    ),
    "Karmaşıklık": (
        "Medyan karmaşıklık skoru, 0 ile 1 arasındadır (0 çok basit, 1 çok karmaşık). "
        "Kurulum boyutu, erken erişim süresi, geliştiricinin oyun sayısı, başarım ve "
        "DLC sayısı, etiketler, platform ve dil sayısından hesaplanır. Emeği değil, "
        "kapsamı yaklaşık olarak gösterir."
    ),
    "Penceredeki çıkışlar": (
        "Arketipte son 24 ayda çıkan oyun sayısı. Rekabet (z) bu sayıdan türetilir."
    ),
    "Etiket": "Steam etiketi. Satırdaki değerler bu etikete sahip oyunlar için hesaplanır.",
    "Olumlu oran": (
        "Olumlu yorumların toplam yorumlara oranı (0 ile 1 arası) medyanı. Oyuncu "
        "memnuniyetinin kaba bir göstergesidir."
    ),
    "Fiyat ($)": "Bu etikete sahip oyunların medyan mağaza fiyatı (ABD doları).",
    "Alt pencere no": (
        "Son 24 aylık pencerenin bölündüğü dilimin sırası. 0 en yeni dilimdir, "
        "numara büyüdükçe dilim geçmişe gider."
    ),
    "Alt pencere başı": "Bu dilimin başlangıç tarihi.",
    "Alt pencere sonu": "Bu dilimin bitiş tarihi.",
    "Eğim": (
        "Bir arketipin dilimler boyunca medyan tahmini satışına uydurulan doğrunun "
        "eğimi (satış/dilim). Dilim numarası geçmişe doğru arttığı için negatif eğim, "
        "satışların yeni oyunlara doğru arttığını gösterir. Betimleyicidir, anlamlılık "
        "iddiası taşımaz ve az dilimde güvenilmezdir."
    ),
    "Eğimde alt pencere sayısı": (
        "Eğimin hesaplandığı, verisi olan dilim sayısı. En az 2 gerekir. Sayı "
        "azaldıkça eğim güvenilirliğini yitirir."
    ),
    "Dönem": "Etiket eğilimi satırlarında kullanılan zaman dilimi.",
}

# Turkish display text for the fixed caveats, keyed by Caveat.key. Unknown keys
# (e.g. the partial-run caveat) fall back to the text supplied by reporting.
_CAVEATS_TR = {
    "steamspy_owner_confidence": (
        "SteamSpy sahip sayısı tahminleri",
        "SteamSpy sahip sayısı tahminleri düşük güvenilirliklidir. Valve 2018'de profil "
        "verilerini kısıtladığı için bu rakamlar o tarihten beri model tahminidir. "
        "Sadece kaba bir sıralama sinyali olarak kullanın, asla kesin veri sanmayın.",
    ),
    "boxleiter_approximation": (
        "Boxleiter satış çarpanı",
        "Boxleiter çarpanı bir yaklaşımdır. Yorum-satış oranı tür, fiyat, çıkış yılı, "
        "bölgesel dağılım ve yorum isteme davranışına göre değişir. Buradaki tür bazlı "
        "aralık belgelenmiş bir varsayımdır, doğrulanmış bir dönüşüm oranı değildir. "
        "Gelir rakamları büyüklük mertebesi göstergesidir.",
    ),
    "simplicity_proxy": (
        "Karmaşıklık kapsamın vekilidir",
        "'Basit' kavramı emeğin değil kapsamın bir vekilidir. Metaveri sanat kalitesini, "
        "oynanış cilasını, pazarlama harcamasını veya kaç prototip denendiğini göremez. "
        "Düşük karmaşıklık skorlu bir oyun yine de bir yıllık emek gerektirmiş olabilir. "
        "Vaka çalışmaları 'kapsamca küçük olması muhtemel ve ticari olarak başarılı' "
        "şeklinde okunmalıdır, 'bu iki haftada yapıldı' şeklinde değil.",
    ),
    "no_scraping_demand_gap": (
        "Eksik talep sinyalleri",
        "Scraping yapılmadığı için bazı talep sinyalleri eksiktir. İstek listesi sayıları, "
        "geçmiş oyuncu sayıları ve fiyat geçmişi resmi uç noktalardan alınamaz. Bu yüzden "
        "'talep' yalnızca yorum hacmi ve sahip sayısı tahminlerinden türetilir.",
    ),
    "survivorship_bias": (
        "Hayatta kalma yanlılığı",
        "Katalog yalnızca yayımlanmış ve hâlâ satışta olan oyunları içerir. Satıştan "
        "kaldırılan başarısız oyunlar ve yarım bırakılan projeler yoktur. Bu durum her "
        "arketipin görünen başarı oranını şişirir.",
    ),
    "competition_historical": (
        "Rekabet geçmişe dayanır",
        "Rekabet yoğunluğu geçmiş çıkışlar üzerinden ölçülür. Tamamlanmış bir oyunun "
        "girdiği pazarı anlatır, bugün başlayan bir oyunun çıkacağı pazarı değil.",
    ),
    "coarse_filter_boundary": (
        "Kaba filtre sert bir sınırdır",
        "Kaba filtre sert bir sınırdır. Veri toplama aşamasında elenen hiçbir oyun sonraki "
        "aşamalarda görünmez. Sınırın görünür kalması için her elenme nedeninin sayısı "
        "analiz bazında saklanır.",
    ),
    "boxleiter_accuracy_limit": (
        "Boxleiter doğruluk sınırı",
        "Gamalytic testine göre, yalnızca yorum çarpanı yöntemiyle oyunların sadece yaklaşık "
        "%43'ü gerçek satışlarının ±%30 aralığına düşüyor. Tahmini satışları bir nokta "
        "tahmini olarak değil, sıralama sinyali olarak kullanın.",
    ),
}


def _status_tr(status: str) -> str:
    return _STATUS_TR.get(status, status)


def _stage_tr(stage: str) -> str:
    return _STAGE_TR.get(stage, stage)


def _render_table(df, empty_message: str, error_prefix: str) -> None:
    """Render a DataFrame with Turkish column headers and per-column help tooltips.

    Columns that are empty for every row are dropped, and a message is shown
    instead of the table when there are no rows at all.
    """
    try:
        if df is None or len(df) == 0:
            st.info(empty_message)
            return
        shown = _localize_columns(df).dropna(axis="columns", how="all")
        shown = shown.loc[:, ~shown.columns.duplicated()]
        config = {
            name: st.column_config.Column(help=_COLUMN_HELP_TR[name])
            for name in shown.columns
            if name in _COLUMN_HELP_TR
        }
        st.dataframe(shown, column_config=config)
    except Exception as e:
        st.warning(f"{error_prefix}: {e}")


def _localize_columns(df):
    """Rename known display columns to Turkish; unknown columns are left as-is."""
    try:
        return df.rename(columns=_COLUMN_TR)
    except AttributeError:
        return df


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours} sa {minutes} dk {secs} sn"
    if minutes:
        return f"{minutes} dk {secs} sn"
    return f"{secs} sn"


def _run_duration_text(run_row, stages) -> str | None:
    """Duration from runs.finished_at, falling back to stage timestamps for older rows."""
    from datetime import datetime

    try:
        if run_row["finished_at"]:
            started = datetime.fromisoformat(run_row["started_at"])
            finished = datetime.fromisoformat(run_row["finished_at"])
            return _format_duration((finished - started).total_seconds())
    except (TypeError, ValueError):
        pass
    starts = [s.started_at for s in stages if s.started_at]
    ends = [s.finished_at for s in stages if s.finished_at]
    if starts and ends:
        return _format_duration((max(ends) - min(starts)).total_seconds())
    return None


def render_caveat_panel(caveats: Sequence[reporting.Caveat]) -> None:
    """Render a fixed expander listing every caveat.

    Args:
        caveats: Typically reporting.interpretive_caveats() plus, when applicable,
            reporting.partial_run_caveat(...) and the 'archetype_cap_relaxed' caveat
            already appended by reporting.load_run_report.

    Behavior:
        - An st.expander (collapsed by default, so it does not dominate the page,
          but always present and always labeled clearly).
        - Each Caveat rendered with its title, body, and a visual marker for severity.
        - Order: caveats are rendered in the order given, not re-sorted.
    """
    severity_icons = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}
    caveat_count = len(caveats)
    with st.expander(f"Yöntem notları ve sınırlılıklar ({caveat_count})"):
        if not caveats:
            st.write("Gösterilecek not yok.")
        else:
            for caveat in caveats:
                icon = severity_icons.get(caveat.severity, "ℹ️")
                title, body = _CAVEATS_TR.get(caveat.key, (caveat.title, caveat.body))
                st.write(f"**{icon} {title}**")
                st.write(body)


def render_new_analysis_page(conn: sqlite3.Connection, settings: Settings) -> None:
    """Render the run-trigger page.

    Args:
        conn: This page's own short-lived connection, opened by main/build_navigation's
            dispatch for this rerun only.
        settings: Loaded once in main and passed down.

    Behavior:
        - Shows the current parameters_version read-only, with a note that
          FORMULATION.md is where the actual values live.
        - A form exposing exactly PipelineConfig's fields: max_catalog_pages,
          request_budget_override, notes. start_stage is NOT exposed here.
        - The Start button is disabled while orchestration.active_run_ids() is
          non-empty (ADR-001: only one writer).
        - On Start: config = PipelineConfig(**form values); run_id =
          orchestration.start_pipeline_async(settings.db_path, config,
          settings=settings); sets st.session_state['active_run_id'], etc.
        - If st.session_state['active_run_id'] is set, render_progress_panel
          is called below the form.
    """
    st.header("Yeni analiz başlat")

    # Display parameters_version read-only
    from steam_analyst.config.parameters import parameters_version

    current_version = parameters_version(settings.parameters_path)
    st.info(
        f"**Parametre sürümü:** {current_version}\n\n"
        "Formül sabitleri FORMULATION.md dosyasında kilitlidir ve bu arayüzden "
        "değiştirilemez. Aşağıda yalnızca bu analize özel ayarlar var."
    )

    # Check if a run is already active
    active_runs = orchestration.active_run_ids()
    can_start = len(active_runs) == 0

    # Form for PipelineConfig fields
    st.subheader("Ayarlar")
    with st.form("new_analysis_form"):
        max_catalog_pages = st.number_input(
            "Katalog sayfa sınırı (isteğe bağlı)",
            min_value=1,
            value=None,
            help=(
                "Steam kataloğundan en fazla kaç sayfa çekileceğini belirler. "
                "Her sayfa yaklaşık 1000 uygulama içerir.\n\n"
                "Boş bırakırsanız tüm katalog taranır. Bu, API hızına bağlı olarak "
                "saatler sürebilir.\n\n"
                "Hızlı deneme için 1-3 girin. Analiz çok daha kısa sürer, ama "
                "az sayfa, az aday demektir. Bu sonuçlar yalnızca hattın çalıştığını "
                "görmek için uygundur, güvenilir bir fırsat analizi için yetersizdir."
            ),
        )
        request_budget_override = st.number_input(
            "İstek bütçesi (isteğe bağlı)",
            min_value=1,
            value=None,
            help=(
                "Bu analizde Steam ve SteamSpy'a atılacak toplam API isteği için "
                "üst sınırdır. Sınıra ulaşılınca analiz kalan işi yapmadan durur.\n\n"
                "Boş bırakırsanız ayar dosyasındaki varsayılan bütçe kullanılır.\n\n"
                "Düşük değer süreyi ve API yükünü sınırlar, ama daha az aday "
                "işlenir. İlk tam taramada varsayılanı değiştirmemeniz önerilir."
            ),
        )
        notes = st.text_area(
            "Not (isteğe bağlı)",
            value="",
            help=(
                "Bu analiz için kendinize not. Sonuçları etkilemez, yalnızca kayıtla "
                "birlikte saklanır. Örneğin hangi ayarı neden denediğinizi yazabilirsiniz."
            ),
        )

        start_disabled_reason = None
        if not can_start:
            start_disabled_reason = (
                "Zaten çalışan bir analiz var (aynı anda yalnızca bir analiz "
                "çalışabilir). Bitmesini bekleyin ya da iptal edin."
            )

        submitted = st.form_submit_button(
            "Analizi başlat",
            disabled=not can_start,
            help=start_disabled_reason
            or "Veri toplama, zenginleştirme ve analiz adımlarını sırayla başlatır.",
        )

        if submitted and can_start:
            try:
                # Build config from form values
                config = orchestration.PipelineConfig(
                    max_catalog_pages=max_catalog_pages if max_catalog_pages else None,
                    request_budget_override=request_budget_override
                    if request_budget_override
                    else None,
                    notes=notes if notes else None,
                    start_stage=orchestration.PipelineStage.ACQUISITION,
                )

                # Start the pipeline
                run_id = orchestration.start_pipeline_async(
                    settings.db_path, config, settings=settings
                )

                # Initialize session state
                st.session_state["active_run_id"] = run_id
                st.session_state["last_event_id"] = 0
                st.session_state["event_log"] = []

                st.success(f"Analiz başlatıldı: {run_id}")
            except Exception as e:
                st.error(f"Analiz başlatılamadı: {e}")

    # Render progress panel if a run is active
    if st.session_state.get("active_run_id"):
        st.divider()
        render_progress_panel(settings.db_path, st.session_state["active_run_id"])


@st.fragment(run_every="2s")
def render_progress_panel(db_path: Path, run_id: str) -> None:
    """Render live progress for one run and poll for updates.

    Args:
        db_path: Opens its own short-lived connection inside this fragment call,
            per ADR-017.
        run_id: The run being watched.

    Behavior:
        - Opens connection, reads run, stages, and new events since last_event_id.
        - Updates session state event_log and advances last_event_id.
        - Renders stage list with status and latest progress value.
        - Cancel button disabled once clicked this session.
        - When run reaches terminal status, stops polling and calls st.rerun().
    """
    # Initialize session state if needed
    if "last_event_id" not in st.session_state:
        st.session_state["last_event_id"] = 0
    if "event_log" not in st.session_state:
        st.session_state["event_log"] = []
    if "_cancel_requested" not in st.session_state:
        st.session_state["_cancel_requested"] = False

    try:
        with storage.connect(db_path) as conn:
            run = storage.get_run(conn, run_id)
            if run is None:
                st.warning(f"{run_id} kaydı veritabanında bulunamadı.")
                return

            stages = storage.read_run_stages(conn, run_id)
            new_events = storage.read_run_events(
                conn, run_id, since_event_id=st.session_state["last_event_id"]
            )

        # Update session state with new events
        if new_events:
            st.session_state["event_log"].extend(new_events)
            st.session_state["last_event_id"] = new_events[-1].event_id

    except Exception as e:
        st.error(f"İlerleme okunamadı: {e}")
        return

    # Render stage status
    st.subheader("İlerleme")
    for stage in stages:
        status_emoji = {"pending": "⏳", "running": "▶️", "succeeded": "✅", "failed": "❌"}[
            stage.status
        ]
        st.write(f"{status_emoji} {_stage_tr(stage.stage)}: {_status_tr(stage.status)}")

    # Render latest progress from event log
    if st.session_state["event_log"]:
        latest_event = st.session_state["event_log"][-1]
        if latest_event.progress_value is not None:
            st.info(f"**Son ilerleme:** {latest_event.progress_value}")

    # Render recent events (with bounded tail for long runs)
    st.subheader("Olay günlüğü")
    event_log = st.session_state["event_log"]
    if len(event_log) > 20:
        with st.expander(f"Tüm günlük ({len(event_log)} olay)"):
            for event in event_log:
                st.write(f"{event.event_id}: {event.message}")
        st.write("**Son olaylar (son 20):**")
        for event in event_log[-20:]:
            st.write(f"{event.event_id}: {event.message}")
    else:
        for event in event_log:
            st.write(f"{event.event_id}: {event.message}")

    # Cancel button
    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "Analizi iptal et",
            disabled=st.session_state["_cancel_requested"],
            key="cancel_button",
        ):
            st.session_state["_cancel_requested"] = True
            try:
                orchestration.cancel_run(run_id)
                st.info("İptal istendi. Analizin durması birkaç saniye sürebilir.")
            except Exception as e:
                st.error(f"İptal edilemedi: {e}")

    # Check if terminal status reached
    if run.status in ("succeeded", "failed", "cancelled"):
        st.success(f"Analiz bitti. Durum: {_status_tr(run.status)}")
        st.rerun()


def render_past_analyses_page(conn: sqlite3.Connection, settings: Settings) -> None:
    """Render the list of past and current runs.

    Args:
        conn: This page's own short-lived connection.
        settings: For settings.db_path, passed to button actions.

    Behavior:
        - Table with run_id, started_at, status, stage completion, metrics, duration.
        - Per row: Open (sets query_params['run_id']), Resume (only for non-succeeded,
          non-active runs), Delete (with 2-step confirmation).
    """
    st.header("Geçmiş analizler")

    try:
        runs_df = storage.list_runs(conn, limit=50)
    except Exception as e:
        st.error(f"Analizler yüklenemedi: {e}")
        return

    if runs_df.empty:
        st.info("Henüz analiz yok.")
        return

    # Display the runs table
    st.subheader("Analizler")
    active_run_ids = orchestration.active_run_ids()

    for idx, row in runs_df.iterrows():
        run_id = row["run_id"]
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 2, 2])

            with col1:
                st.write(f"**Analiz no:** {run_id}")
                st.write(f"**Başlangıç:** {row['started_at']}")
                st.write(f"**Durum:** {_status_tr(row['status'])}")
                if "candidate_count" in row and row["candidate_count"]:
                    st.write(f"**Aday sayısı:** {row['candidate_count']}")

            with col2:
                st.write("**Aşamalar:**")
                stages = storage.read_run_stages(conn, run_id)
                if stages:
                    for stage in stages:
                        st.write(f"{_stage_tr(stage.stage)}: {_status_tr(stage.status)}")
                else:
                    st.write("Hiçbir aşama başlamadı.")
                duration_text = _run_duration_text(row, stages)
                if duration_text:
                    st.write(f"**Süre:** {duration_text}")

            with col3:
                st.write("**İşlemler:**")
                # Open button
                if st.button(
                    "Aç",
                    key=f"open_{run_id}",
                    help="Sonuçları ayrıntılı sayfada gösterir.",
                ):
                    st.switch_page(
                        _NAV_PAGES["detail"], query_params={"run_id": run_id}
                    )

                # Resume button (only for non-succeeded, non-active runs)
                if row["status"] != "succeeded" and run_id not in active_run_ids:
                    if st.button(
                        "Devam et",
                        key=f"resume_{run_id}",
                        help="Yarım kalan analizi kaldığı aşamadan sürdürür.",
                    ):
                        try:
                            resume_run_id = orchestration.resume_run(
                                settings.db_path, run_id, settings=settings
                            )
                            st.session_state["active_run_id"] = resume_run_id
                            st.session_state["last_event_id"] = 0
                            st.session_state["event_log"] = []
                            st.success(f"Analiz sürdürülüyor: {resume_run_id}")
                        except orchestration.PipelineError as e:
                            st.warning(f"Devam ettirilemedi: {e}")

                # Delete button with confirmation
                delete_key = f"delete_{run_id}"
                confirm_key = f"confirm_delete_{run_id}"

                if delete_key not in st.session_state:
                    st.session_state[delete_key] = False
                if confirm_key not in st.session_state:
                    st.session_state[confirm_key] = False

                if not st.session_state[delete_key]:
                    if st.button(
                        "Sil",
                        key=f"delete_btn_{run_id}",
                        help="Analizi ve ona ait tüm verileri kalıcı olarak siler.",
                    ):
                        st.session_state[delete_key] = True
                        st.rerun()
                else:
                    if not st.session_state[confirm_key]:
                        st.warning(f"{run_id} analizi silinsin mi?")
                        if st.button("Evet, sil", key=f"yes_delete_{run_id}"):
                            st.session_state[confirm_key] = True
                            st.rerun()
                        if st.button("Vazgeç", key=f"cancel_delete_{run_id}"):
                            st.session_state[delete_key] = False
                            st.rerun()
                    else:
                        try:
                            storage.delete_run(conn, run_id)
                            st.success(f"{run_id} silindi")
                            st.session_state[delete_key] = False
                            st.session_state[confirm_key] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Silinemedi: {e}")
                            st.session_state[delete_key] = False
                            st.session_state[confirm_key] = False


def _matrix_with_raw_columns(df):
    """Invert the report view's display headers back to the analysis column names."""
    inverse = {
        display: raw
        for raw, display in reporting.views.OPPORTUNITY_MATRIX_COLUMN_MAPPING.items()
    }
    return df.rename(columns=inverse)


def _group_name(label) -> str:
    """Turn a raw archetype label such as 'Archetype 23' into a Turkish group name."""
    text = str(label) if label is not None else "bilinmeyen grup"
    return text.replace("Archetype", "Grup")


def _complexity_bounds_frozen(settings) -> bool | None:
    """Return whether complexity_bounds is set in the parameters file (None if unreadable)."""
    try:
        from .info_page import _load_parameters

        bounds = _load_parameters(settings).get("enrichment", {}).get("complexity_bounds")
        return bool(bounds)
    except Exception:
        return None


def _top_games_frame(case_studies, n: int = 10) -> pd.DataFrame:
    """Build the multi-parameter table of the top-n case-study games (ranked order)."""
    rows = []
    for c in list(case_studies)[:n]:
        pct = c.review_positive_pct
        price = c.price_usd
        rows.append(
            {
                "Oyun": c.name,
                "Grup": _group_name(c.archetype_label) if c.archetype_label else "-",
                "Tahmini satış (adet)": round(c.estimated_sales_band[1]),
                "Tahmini net gelir ($)": round(c.estimated_revenue_net_usd),
                "Karmaşıklık (0-1)": round(c.complexity_score, 2),
                "Olumlu yorum (%)": None if pct != pct else round(pct * 100),
                "Yorum sayısı": c.review_count,
                "Fiyat ($)": None if price != price else round(price, 2),
                "Çıkış tarihi": c.release_date,
            }
        )
    return pd.DataFrame(rows)


def _render_simple_summary(report, bounds_frozen: bool | None = None) -> None:
    """Plain-language summary at the top of the detail page for non-expert readers."""
    try:
        funnel = report.funnel
        st.subheader("Kısaca sonuç")
        with st.container(border=True):
            st.write(
                "Bu analiz, Steam'deki oyunlar arasından **az kişiyle, kısa sürede "
                "yapılabilecek kadar basit** olup da **iyi satmış görünenleri** ve "
                "hangi oyun türlerinde (etiket kombinasyonlarında) fırsat olabileceğini "
                "arar. Aşağıda en önemli bulgular sade bir dille özetlenmiştir."
            )
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "Taranan oyun",
                    f"{funnel.catalog_size:,}",
                    help="Steam kataloğundan çekilen toplam uygulama sayısı.",
                )
            with col2:
                st.metric(
                    "Değerlendirilen oyun",
                    f"{funnel.candidate_count:,}",
                    help="Yeterli yorumu olan, 2020 ve sonrası çıkmış ve bilinen büyük "
                    "yayıncıların listesinde yer almayan oyunlar. Liste kapsamlı "
                    "değildir, bu yüzden büyük yapımlar yine de girebilir. Sonuçlar "
                    "yalnızca aşağıdaki 'basit sayılan' dilim üzerinden hesaplanır.",
                )
            with col3:
                st.metric(
                    "Basit sayılan oyun",
                    f"{funnel.simple_subset_size:,}",
                    help="Değerlendirilen oyunlar içinde yapımı en az kapsamlı "
                    "görünen %40'lık dilim.",
                )

            if bounds_frozen is False:
                st.error(
                    "**Önemli uyarı: 'basit oyun' ayrımı şu an güvenilir değil.** "
                    "Karmaşıklık skorunun normalizasyon sınırları henüz belirlenmediği "
                    "için başarım, DLC, dil ve geliştirici oyun sayısı skora hiç "
                    "yansımıyor, skor yalnızca etiketlere ve platform sayısına göre "
                    "değişiyor. Bu yüzden Cyberpunk 2077 ya da Baldur's Gate 3 gibi büyük "
                    "yapımlar da 'basit' sayılabiliyor. Aşağıdaki sonuçlar "
                    "'basit oyunlar' için değil, genel olarak başarılı oyunlar için "
                    "bir fikir verir. Ayrıntı için Bilgi sayfasına bakın."
                )

            if funnel.candidate_count == 0 or funnel.simple_subset_size == 0:
                st.info(
                    "Bu çalıştırmada yorum yapılacak kadar oyun kalmadı. Daha fazla "
                    "katalog sayfası ile yeni bir analiz başlatın."
                )
                return

            matrix = report.opportunity_matrix
            if matrix is not None and len(matrix) > 0:
                matrix = _matrix_with_raw_columns(matrix)
                ranked = matrix.sort_values("opportunity_score", ascending=False)
                top = ranked.iloc[0]
                st.markdown(
                    f"**Öne çıkan oyun grubu:** {_group_name(top['label'])}. "
                    f"{int(top['n_games'])} oyundan oluşuyor, son 24 ayda "
                    f"{int(top['releases_in_window'])} oyun çıkmış, bu oyunların "
                    f"ortanca tahmini satışı yaklaşık {top['median_estimated_sales_mid']:,.0f} "
                    "adet. Talep, rekabet ve basitlik birlikte değerlendirildiğinde skoru "
                    "diğer gruplardan yüksek çıktı."
                )
                chart = ranked.head(5).copy()
                chart["Grup"] = chart["label"].map(_group_name)
                st.markdown("**En elverişli 5 oyun grubu** (yüksek skor daha elverişli)")
                st.bar_chart(
                    chart.set_index("Grup")[["opportunity_score"]].rename(
                        columns={"opportunity_score": "Fırsat skoru"}
                    ),
                    horizontal=True,
                    sort=False,
                )
            else:
                st.warning(
                    "Bu çalıştırmada oyun grupları oluşturulamadı, çünkü analiz az "
                    "sayıda oyunla çalıştı. Bu yüzden hangi grubun daha elverişli "
                    "olduğu söylenemiyor. Aşağıdaki örnek oyunlar ve etiketler yalnızca "
                    "fikir verir. Daha güvenilir bir sonuç için daha fazla katalog "
                    "sayfası taratın."
                )

            cases = list(report.case_studies or [])
            if cases:
                top_cases = cases[:5]
                names = ", ".join(c.name for c in top_cases)
                st.markdown(
                    f"**Az emekle iyi satmış görünen örnekler:** {names}."
                )
                st.markdown(
                    "**En elverişli 10 oyun** (tahmini net gelirin karmaşıklığa oranına "
                    "göre sıralı; satış, gelir, karmaşıklık, yorum, fiyat ve çıkış tarihi "
                    "birlikte gösterilir)"
                )
                st.dataframe(
                    _top_games_frame(cases, 10), hide_index=True, width="stretch"
                )
                if not (matrix is not None and len(matrix) > 0):
                    frame = pd.DataFrame(
                        {"Tahmini satış (adet)": [c.estimated_sales_band[1] for c in top_cases]},
                        index=[c.name for c in top_cases],
                    )
                    st.markdown("**Bu örneklerin tahmini satışı** (kaba tahmin)")
                    st.bar_chart(frame, horizontal=True, sort=False)

            st.markdown(
                "**Nasıl okunmalı?**\n"
                "- Satış rakamları Steam yorum sayısından yapılan kaba tahmindir, "
                "kesin değildir.\n"
                "- 'Basit' oyun, yapımı küçük kapsamlı görünen demektir, gerçekte az "
                "emekle yapıldığı kanıtlanmış değildir.\n"
                "- Bu sonuçlar bir başarı garantisi değil, incelemeye değer yönlerdir."
            )
    except Exception as e:
        st.warning(f"Özet gösterilemedi: {e}")


def _case_rationale_tr(case_study) -> str:
    """Build the Turkish rationale sentence for one case study from its fields."""
    pct = case_study.review_positive_pct
    positive = "olumlu oranı bilinmiyor" if pct != pct else f"%{pct * 100:.0f} olumlu"
    price = case_study.price_usd
    price_text = "fiyatı bilinmiyor" if price != price else f"${price:.2f}"
    archetype = case_study.archetype_label or "bilinmeyen arketip"
    return (
        f"{case_study.review_count:,} yorum ({positive}) ve {price_text} fiyatla "
        f"{archetype} içinde yer alıyor. Karmaşıklık skoru "
        f"{case_study.complexity_score:.2f} (0 en basit, 1 en karmaşık). Tahmini net "
        "gelirin karmaşıklığa oranı (etkin getiri) seçim sıralamasında üst sıralarda "
        "olduğu için vaka çalışması olarak seçildi."
    )


def _render_opportunity_charts(df) -> None:
    """Bar chart of opportunity score and demand/competition scatter per archetype."""
    try:
        if df is None or len(df) == 0:
            return
        data = _matrix_with_raw_columns(df)
        data["label"] = data["label"].fillna(data["cluster_id"].astype(str))
        ranked = data.sort_values("opportunity_score", ascending=False).head(15)
        st.markdown("**Arketiplere göre fırsat skoru** (ilk 15)")
        st.bar_chart(
            ranked.set_index("label")[["opportunity_score"]].rename(
                columns={"opportunity_score": "Fırsat skoru"}
            ),
            horizontal=True,
            sort=False,
        )
        st.markdown("**Talep ve rekabet** (her nokta bir arketip; sol üst en elverişli bölge)")
        scatter = data.rename(
            columns={"demand_z": "Talep (z)", "competition_z": "Rekabet (z)"}
        )
        st.scatter_chart(scatter, x="Rekabet (z)", y="Talep (z)", size="n_games")
    except Exception as e:
        st.warning(f"Fırsat grafikleri gösterilemedi: {e}")


def _render_tag_summary_chart(df) -> None:
    """Bar chart of the most frequent tags in the simple subset."""
    try:
        if df is None or len(df) == 0 or "N" not in df.columns:
            return
        top = df.sort_values("N", ascending=False).head(15)
        st.markdown("**En sık görülen etiketler** (basit oyun alt kümesindeki oyun sayısı)")
        st.bar_chart(
            top.set_index("Tag")[["N"]].rename(columns={"N": "Oyun sayısı"}),
            horizontal=True,
            sort=False,
        )
    except Exception as e:
        st.warning(f"Etiket grafiği gösterilemedi: {e}")


def _render_trend_chart(df) -> None:
    """Line chart of median estimated sales per sub-window, one line per archetype."""
    try:
        if df is None or len(df) == 0:
            return
        data = df.dropna(subset=["sub_window_end", "median_estimated_sales_mid"]).copy()
        if data.empty:
            return
        data["Arketip"] = "Küme " + data["cluster_id"].astype(int).astype(str)
        wide = data.pivot_table(
            index="sub_window_end",
            columns="Arketip",
            values="median_estimated_sales_mid",
            aggfunc="median",
        ).sort_index()
        st.markdown(
            "**Alt pencerelere göre medyan tahmini satış** (yatay eksen: dilimin bitiş "
            "tarihi; boşluklar oyun çıkmayan dilimlerdir)"
        )
        st.line_chart(wide)
    except Exception as e:
        st.warning(f"Eğilim grafiği gösterilemedi: {e}")


def _render_case_study_chart(case_studies) -> None:
    """Bar chart of the estimated mid sales of the selected case studies."""
    try:
        frame = pd.DataFrame(
            {
                "Oyun": [c.name for c in case_studies],
                "Tahmini satış (orta)": [c.estimated_sales_band[1] for c in case_studies],
            }
        ).set_index("Oyun")
        st.markdown("**Vaka çalışmalarının tahmini satışı** (orta değer, kaba sinyal)")
        st.bar_chart(frame, horizontal=True, sort=False)
    except Exception as e:
        st.warning(f"Vaka grafiği gösterilemedi: {e}")


def render_analysis_detail_page(conn: sqlite3.Connection, settings: Settings) -> None:
    """Render one run's results.

    Args:
        conn: This page's own short-lived connection.
        settings: For settings.db_path, kept for signature consistency.

    Behavior:
        - Read run_id from query_params; show empty state if missing/unknown.
        - Load report once, render caveat panel, results, and progress if running.
        - Show 'not enough data' message for empty candidate sets.
    """
    run_id = st.query_params.get("run_id")

    if not run_id:
        st.header("Analiz ayrıntısı")
        st.info("Analiz seçilmedi. Lütfen Geçmiş analizler sayfasından bir analiz seçin.")
        if st.button("Geçmiş analizlere git"):
            st.switch_page(_NAV_PAGES["past"])
        return

    try:
        report = reporting.load_run_report(conn, run_id)
    except reporting.ReportNotAvailable:
        st.header("Analiz ayrıntısı")
        st.warning(f"{run_id} analizi bulunamadı.")
        if st.button("Geçmiş analizlere git"):
            st.switch_page(_NAV_PAGES["past"])
        return
    except Exception as e:
        st.error(f"Rapor yüklenemedi: {e}")
        return

    st.header(f"Analiz ayrıntısı: {run_id}")

    _render_simple_summary(report, _complexity_bounds_frozen(settings))

    # Render caveats near the top
    render_caveat_panel(report.caveats)

    # If partial, show partial_run_caveat and progress panel if running
    if report.is_partial:
        partial_caveat = reporting.partial_run_caveat(
            report.missing_stages, report.run
        )
        st.warning(
            f"**{partial_caveat.title}**\n\n{partial_caveat.body}"
        )

        if report.run.status == "running":
            st.divider()
            render_progress_panel(settings.db_path, run_id)

    # Render results
    st.divider()
    st.subheader("Sonuçlar")

    # Check for empty candidate set
    if report.funnel.candidate_count == 0:
        st.info(
            "**Yeterli veri yok.** Hiçbir oyun kaba filtreyi geçemedi. "
            "Daha büyük bir katalog taraması çalıştırmayı deneyin."
        )
        return

    # Check if simplicity subset is too small
    if report.funnel.simple_subset_size == 0:
        st.info(
            "**Yeterli veri yok.** Hiçbir oyun basitlik filtresini geçemedi. "
            "Aday kümesinde hedeflenen karmaşıklık düzeyine uyan oyun olmayabilir."
        )
        return

    # Opportunity matrix
    st.subheader("Fırsat matrisi")
    st.caption(
        "Her satır bir arketiptir (etiket kombinasyonları birbirine benzeyen oyunların "
        "kümesi). Fırsat skoru = 0,40 x talep - 0,30 x rekabet + 0,30 x basitlik. "
        "Üç bileşen de arketipler arasında z-skoruna çevrilmiştir (0 = ortalama). "
        "Skor parasal bir değer değil, arketipleri birbiriyle sıralamak için "
        "kullanılan göreli bir ölçüdür. Ayrıntı için Bilgi sayfasına bakın."
    )
    _render_table(
        report.opportunity_matrix,
        "Fırsat matrisi boş. Hiçbir arketip (etiket kümesi) en az 5 oyuna ulaşamadı. "
        "Bu genellikle analizin az sayıda adayla (küçük katalog taraması) çalıştığını "
        "gösterir. Daha fazla katalog sayfası ile yeni bir analiz başlatın.",
        "Fırsat matrisi gösterilemedi",
    )
    _render_opportunity_charts(report.opportunity_matrix)

    st.subheader("Etiket özeti")
    st.caption(
        "Basit oyun alt kümesinde her Steam etiketi için o etikete sahip oyunların "
        "medyan karmaşıklığı, medyan tahmini satışı (Boxleiter orta değeri), medyan "
        "olumlu yorum oranı ve medyan fiyatı. Bir oyun birden fazla etiket taşıdığı için "
        "aynı oyun birden çok satırda sayılır. Oyun sayısı (N) küçükse medyanlar "
        "tek bir oyundan etkilenir."
    )
    _render_table(
        report.tag_summary,
        "Etiket özeti boş.",
        "Etiket özeti gösterilemedi",
    )
    _render_tag_summary_chart(report.tag_summary)

    st.subheader("Etiket eğilimleri")
    st.caption(
        "Her arketip için son 24 aylık pencere 4'er aylık 6 dilime bölünür ve her "
        "dilimde o arketipte çıkan oyunların medyan tahmini satışı hesaplanır. "
        "Burada çıkış sayısı değil, çıkan oyunların medyan satışı gösterilir. "
        "Dilim numarası 0 en yeni dilimdir ve numara büyüdükçe geçmişe gidilir. "
        "Eğim, dilim numarasına karşı medyan satışa uydurulan doğrusal (OLS) regresyon "
        "doğrusunun eğimidir. Numara geçmişe doğru arttığı için negatif eğim, yeni "
        "çıkan oyunların eskilere göre daha yüksek satış yaptığını, pozitif eğim ise "
        "tersini gösterir. Bir dilimde hiç oyun çıkmadıysa o dilim hesaba katılmaz ve "
        "eğim için en az 2 dilim gerekir. Bu değer betimleyicidir, istatistiksel "
        "anlamlılık testi içermez ve az dilim ya da az oyunla güvenilir değildir."
    )
    _render_table(
        report.tag_trends,
        "Etiket eğilimi verisi yok. Eğilim, yalnızca oluşan arketipler için hesaplanır.",
        "Etiket eğilimleri gösterilemedi",
    )
    _render_trend_chart(report.tag_trends)

    # Case studies
    st.subheader("Vaka çalışmaları")
    st.markdown(
        "**Vaka çalışması nedir?** Fırsat matrisi arketipleri özetler. Vaka çalışmaları "
        "ise bu arketiplerin içinde, *az emekle ticari olarak başarılı olduğu "
        "görünen* somut oyun örnekleridir. Amaç, bir arketipin gerçekte nasıl "
        "göründüğünü tek tek oyunlar üzerinden incelemektir.\n\n"
        "**Nasıl seçilir?**\n"
        "1. Yalnızca gelir tahmini ve karmaşıklık skoru hesaplanabilen oyunlar "
        "değerlendirilir (ücretsiz oyunlar ve karmaşıklığı bilinmeyenler dışarıda kalır) "
        "ve oyunun bir arketip kümesine atanmış olması gerekir.\n"
        "2. Oyunlar *etkin getiri* değerine göre büyükten küçüğe sıralanır. Etkin getiri, "
        "tahmini net gelirin karmaşıklık skoruna (+0,05) bölünmesidir. Yani kabaca "
        "'kapsam başına kazanç'tır.\n"
        "3. Çeşitlilik için sıradan en fazla 15 oyun alınır. Bir arketipten en fazla "
        "2, bir geliştiriciden en fazla 1 oyun seçilir. 15'e ulaşılamazsa arketip "
        "sınırı bir kez 3'e gevşetilir (geliştirici sınırı hiç gevşetilmez).\n\n"
        "**Dikkat:** Gelir, yorum sayısından Boxleiter yöntemiyle çıkarılan kaba bir "
        "tahmindir. Karmaşıklık skoru da emeği değil kapsamı yaklaşık olarak gösterir. "
        "Bu oyunların gerçekten az emekle yapıldığı kanıtlanmış bir sonuç olarak "
        "okunmamalıdır. Yalnızca 'incelemeye değer adaylar' olarak değerlendirin."
    )
    if not report.case_studies:
        st.info("Gösterilecek vaka çalışması yok.")
    else:
        _render_case_study_chart(report.case_studies)
        for case_study in report.case_studies:
            with st.expander(f"{case_study.name} (appid={case_study.appid})"):
                st.write(f"**Gerekçe:** {_case_rationale_tr(case_study)}")
                if case_study.archetype_label:
                    st.write(f"**Arketip:** {case_study.archetype_label}")
                st.write(
                    f"**Geliştirici:** {case_study.developer} | "
                    f"**Çıkış:** {case_study.release_date} | "
                    f"**Fiyat:** ${case_study.price_usd:.2f}"
                )
                pct = case_study.review_positive_pct
                positive_text = (
                    "olumlu oran bilinmiyor" if pct != pct else f"%{pct * 100:.0f} olumlu"
                )
                st.write(
                    f"**Yorumlar:** {case_study.review_count:,} "
                    f"({positive_text})"
                )
                low, mid, high = case_study.estimated_sales_band
                revenue = case_study.estimated_revenue_net_usd
                revenue_text = "bilinmiyor" if revenue != revenue else f"${revenue:,.0f}"
                st.write(
                    f"**Tahmini satış (kaba aralık):** {low:,.0f} - {high:,.0f} "
                    f"(orta {mid:,.0f}) | **Tahmini net gelir:** {revenue_text}"
                )
                st.write(f"**Karmaşıklık skoru:** {case_study.complexity_score:.2f}")
                if case_study.top_tags:
                    st.write(f"**Öne çıkan etiketler:** {', '.join(case_study.top_tags)}")
                if case_study.complexity_drivers:
                    drivers = ", ".join(
                        f"{name} ({weight:.2f})"
                        for name, weight in case_study.complexity_drivers
                    )
                    st.write(f"**Karmaşıklığı artıranlar:** {drivers}")
                st.markdown(f"[Steam mağaza sayfası]({case_study.store_url})")

    # Funnel visualization
    st.subheader("Huni özeti")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Katalog boyutu", report.funnel.catalog_size)
    with col2:
        st.metric("Adaylar", report.funnel.candidate_count)
    with col3:
        st.metric("Basit oyunlar", report.funnel.simple_subset_size)
    st.caption(
        "Katalog: taranan Steam uygulamaları. Adaylar: kaba filtreyi geçenler. "
        "Basit oyunlar: adaylar içinde karmaşıklık skoru en düşük %40'lık dilime girenler."
    )
    funnel_df = pd.DataFrame(
        {
            "Oyun sayısı": [
                report.funnel.catalog_size,
                report.funnel.candidate_count,
                report.funnel.simple_subset_size,
            ]
        },
        index=["Katalog", "Adaylar", "Basit oyunlar"],
    )
    st.bar_chart(funnel_df, horizontal=True, sort=False)
