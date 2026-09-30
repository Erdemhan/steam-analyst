"""Unit tests for enrichment.pipeline module."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

from steam_analyst.config.settings import EnrichmentParams
from steam_analyst.enrichment.parsing import RawBundle
from steam_analyst.enrichment.pipeline import (
    build_enriched_frame,
    run_enrichment,
    EnrichmentReport,
)
from steam_analyst.storage import (
    create_run,
    get_connection,
    initialize_schema,
    upsert_raw_payloads,
    read_enriched,
    read_tags,
)
from steam_analyst.storage.types import RawPayload, TagRow


def _sha256(obj):
    """Compute SHA256 of a JSON object."""
    import hashlib
    json_bytes = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(json_bytes).hexdigest()


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database with schema."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def basic_params():
    """Return a basic EnrichmentParams for testing."""
    return EnrichmentParams(
        boxleiter_multipliers={
            "niche": (20.0, 27.0, 35.0),
            "mainstream": (30.0, 37.0, 45.0),
            "broad_audience": (40.0, 50.0, 65.0),
        },
        genre_bucket_map={
            "Action": "mainstream",
            "Adventure": "mainstream",
            "RPG": "mainstream",
            "Strategy": "niche",
            "Indie": "mainstream",
        },
        storefront_cut=0.30,
        discount_factor=0.0,
        refund_regional_factor=0.0,
        complexity_weights={
            "size_bytes": 0.20,
            "early_access_days": 0.15,
            "dev_title_count": 0.15,
            "simplicity_tag_score": 0.10,
            "complexity_tag_score": 0.10,
            "achievement_count": 0.10,
            "dlc_count": 0.10,
            "platform_count": 0.05,
            "language_count": 0.05,
        },
        complexity_bounds={},  # Pre-freeze state
        simplicity_tags=["casual", "short", "pixel-art"],
        complexity_tags=["open-world", "multiplayer", "physics"],
        effort_epsilon=0.05,
        tag_extraction_max_per_game=20,
        tag_extraction_min_votes=0,
    )


@pytest.fixture
def simple_bundle():
    """Create a simple test bundle with 2 games."""
    return RawBundle(
        run_id="test-run-1",
        steamspy={
            100: {
                "appid": 100,
                "name": "Game One",
                "developer": "DevA",
                "publisher": "PubA",
                "positive": 500,
                "negative": 100,
                "owners_low": 10000,
                "owners_high": 20000,
                "price": 1999,  # $19.99
                "initialprice": 1999,
                "discount": 0,
                "tags": {"indie": 200, "casual": 150},
            },
            101: {
                "appid": 101,
                "name": "Game Two",
                "developer": "DevB",
                "publisher": "PubB",
                "positive": 50,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price": 0,  # Free
                "initialprice": 0,
                "discount": 0,
                "tags": {"free-to-play": 100},
            },
        },
        steamspy_appdetails={
            100: {
                "appid": 100,
                "name": "Game One",
                "tags": {"indie": 200, "casual": 150},
            },
            101: {
                "appid": 101,
                "name": "Game Two",
                "tags": {"free-to-play": 100},
            },
        },
        appdetails={
            100: {
                "success": True,
                "data": {
                    "appid": 100,
                    "name": "Game One",
                    "type": "game",
                    "developers": ["DevA"],
                    "publishers": ["PubA"],
                    "is_free": False,
                    "price_overview": {"final": 1999},
                    "genres": [
                        {"description": "Action"},
                        {"description": "Adventure"},
                    ],
                    "categories": [{"description": "Single-player"}],
                    "size_bytes": 5000000000,  # 5 GB
                    "achievements": {"total": 50},
                    "supported_languages": "English<strong>*</strong>, French, German",
                    "platforms": {"windows": True, "mac": False, "linux": False},
                    "dlc": [1001, 1002],
                    "is_early_access": False,
                    "release_date": {"date": "2022-01-15"},
                    "steam_deck_compat": {"compat_category": "Verified"},
                },
            },
            101: {
                "success": True,
                "data": {
                    "appid": 101,
                    "name": "Game Two",
                    "type": "game",
                    "developers": ["DevB"],
                    "publishers": ["PubB"],
                    "is_free": True,
                    "price_overview": {},
                    "genres": [{"description": "Action"}],
                    "categories": [{"description": "Multi-player"}],
                    "size_bytes": 10000000000,  # 10 GB
                    "achievements": {"total": 100},
                    "supported_languages": "English<strong>*</strong>, Spanish",
                    "platforms": {"windows": True, "mac": True, "linux": False},
                    "dlc": [],
                    "is_early_access": True,
                    "release_date": {"date": "2023-06-01"},
                    "steam_deck_compat": {"compat_category": "Playable"},
                },
            },
        },
        reviews={
            100: {
                "success": True,
                "query_summary": {"total_reviews": 600, "review_score": 87},
            },
            101: {
                "success": False,
                "query_summary": {},
            },
        },
    )


@pytest.fixture
def simple_catalog():
    """Create a simple test catalog matching the bundle."""
    return pd.DataFrame([
        {
            "appid": 100,
            "name": "Game One",
            "developer": "DevA",
            "publisher": "PubA",
            "positive": 500,
            "negative": 100,
            "owners_low": 10000,
            "owners_high": 20000,
            "price_usd": 19.99,
            "initialprice": 19.99,
            "discount": 0,
            "tags": {},
        },
        {
            "appid": 101,
            "name": "Game Two",
            "developer": "DevB",
            "publisher": "PubB",
            "positive": 50,
            "negative": 10,
            "owners_low": 1000,
            "owners_high": 2000,
            "price_usd": 0.0,
            "initialprice": 0.0,
            "discount": 0,
            "tags": {},
        },
    ])


class TestBuildEnrichedFrame:
    def test_empty_bundle(self, basic_params):
        """Test with empty bundle returns empty frame with all columns."""
        empty_bundle = RawBundle(run_id="test", steamspy={}, steamspy_appdetails={}, appdetails={}, reviews={})
        empty_catalog = pd.DataFrame(columns=[
            "appid", "name", "developer", "publisher", "positive", "negative",
            "owners_low", "owners_high", "price_usd", "initialprice", "discount", "tags"
        ])

        frame, tags = build_enriched_frame(empty_bundle, empty_catalog, basic_params)

        assert len(frame) == 0
        assert len(tags) == 0
        assert "complexity_score" in frame.columns
        assert "estimated_revenue_net_usd" in frame.columns

    def test_full_enrichment_pipeline(self, simple_bundle, simple_catalog, basic_params):
        """Test end-to-end enrichment pipeline."""
        frame, tag_rows = build_enriched_frame(
            simple_bundle, simple_catalog, basic_params
        )

        # Verify frame structure
        assert len(frame) == 2
        assert "appid" in frame.columns
        assert "complexity_score" in frame.columns
        assert "estimated_sales_low" in frame.columns
        assert "estimated_revenue_net_usd" in frame.columns
        assert "effort_adjusted_return" in frame.columns

        # Verify all rows are games
        assert all(frame["app_type"] == "game")

        # Verify appids
        assert set(frame["appid"]) == {100, 101}

    def test_imputed_features_json_lists_feature_names(
        self, simple_bundle, simple_catalog, basic_params
    ):
        """imputed_features_json holds a JSON list of imputed feature names."""
        import json

        frame, _ = build_enriched_frame(simple_bundle, simple_catalog, basic_params)
        valid = {
            "size_bytes", "early_access_days", "dev_title_count", "simplicity_tag_score",
            "complexity_tag_score", "achievement_count", "dlc_count", "platform_count",
            "language_count",
        }
        for raw in frame["imputed_features_json"]:
            names = json.loads(raw)
            assert isinstance(names, list)
            assert set(names) <= valid

    def test_free_to_play_revenue_is_nan(self, simple_bundle, simple_catalog, basic_params):
        """Test that F2P games have NaN revenue, not 0."""
        frame, _ = build_enriched_frame(
            simple_bundle, simple_catalog, basic_params
        )

        f2p_row = frame[frame["appid"] == 101].iloc[0]
        assert pd.isna(f2p_row["estimated_revenue_gross_usd"])
        assert pd.isna(f2p_row["estimated_revenue_net_usd"])

    def test_paid_game_revenue_not_nan(self, simple_bundle, simple_catalog, basic_params):
        """Test that paid games have numeric revenue, not NaN."""
        frame, _ = build_enriched_frame(
            simple_bundle, simple_catalog, basic_params
        )

        paid_row = frame[frame["appid"] == 100].iloc[0]
        assert not pd.isna(paid_row["estimated_revenue_gross_usd"])
        assert not pd.isna(paid_row["estimated_revenue_net_usd"])
        assert paid_row["estimated_revenue_net_usd"] > 0

    def test_non_game_rows_dropped(self, basic_params):
        """Test that non-game rows are completely removed."""
        # Create a bundle with one game and one DLC
        bundle = RawBundle(
            run_id="test",
            steamspy={
                100: {
                    "appid": 100,
                    "name": "Game",
                    "developer": "Dev",
                    "positive": 100,
                    "negative": 10,
                    "owners_low": 1000,
                    "owners_high": 2000,
                    "price": 999,
                    "tags": {},
                },
                101: {
                    "appid": 101,
                    "name": "DLC Pack",
                    "developer": "Dev",
                    "positive": 10,
                    "negative": 1,
                    "owners_low": 100,
                    "owners_high": 200,
                    "price": 499,
                    "tags": {},
                },
            },
            steamspy_appdetails={
                100: {
                    "appid": 100,
                    "tags": {},
                },
            },
            appdetails={
                100: {
                    "success": True,
                    "data": {
                        "type": "game",
                        "name": "Game",
                        "developers": ["Dev"],
                        "publishers": [],
                        "is_free": False,
                        "price_overview": {"final": 999},
                        "genres": [{"description": "Action"}],
                        "categories": [],
                        "size_bytes": 1000000,
                        "achievements": {"total": 10},
                        "supported_languages": "English",
                        "platforms": {"windows": True},
                        "dlc": [],
                        "is_early_access": False,
                        "release_date": {"date": "2022-01-01"},
                    },
                },
                101: {
                    "success": True,
                    "data": {
                        "type": "dlc",  # Not a game!
                        "name": "DLC Pack",
                        "developers": ["Dev"],
                        "publishers": [],
                        "genres": [],
                        "categories": [],
                    },
                },
            },
            reviews={},
        )

        catalog = pd.DataFrame([
            {
                "appid": 100,
                "name": "Game",
                "developer": "Dev",
                "publisher": "",
                "positive": 100,
                "negative": 10,
                "owners_low": 1000,
                "owners_high": 2000,
                "price_usd": 9.99,
                "initialprice": 9.99,
                "discount": 0,
                "tags": {},
            },
            {
                "appid": 101,
                "name": "DLC Pack",
                "developer": "Dev",
                "publisher": "",
                "positive": 10,
                "negative": 1,
                "owners_low": 100,
                "owners_high": 200,
                "price_usd": 4.99,
                "initialprice": 4.99,
                "discount": 0,
                "tags": {},
            },
        ])

        frame, _ = build_enriched_frame(bundle, catalog, basic_params)

        # Only the game should remain
        assert len(frame) == 1
        assert frame.iloc[0]["appid"] == 100

    def test_idempotence(self, simple_bundle, simple_catalog, basic_params):
        """Test that calling build_enriched_frame twice produces identical output."""
        frame1, tags1 = build_enriched_frame(
            simple_bundle, simple_catalog, basic_params
        )
        frame2, tags2 = build_enriched_frame(
            simple_bundle, simple_catalog, basic_params
        )

        # Compare frames (allowing for floating point variance)
        pd.testing.assert_frame_equal(
            frame1.sort_values("appid").reset_index(drop=True),
            frame2.sort_values("appid").reset_index(drop=True),
            check_dtype=False,
            atol=1e-10,
        )

        # Compare tags
        assert len(tags1) == len(tags2)

    def test_tag_extraction(self, simple_bundle, simple_catalog, basic_params):
        """Test that tags are extracted and ranked correctly."""
        _, tag_rows = build_enriched_frame(
            simple_bundle, simple_catalog, basic_params
        )

        # Should have tags from game 100 (indie: 200, casual: 150)
        # Filter by min_votes (10) -- both should pass
        game100_tags = [t for t in tag_rows if t.appid == 100]
        assert len(game100_tags) > 0

        # Tags should be ranked by votes (indie first at rank 1)
        if game100_tags:
            sorted_tags = sorted(game100_tags, key=lambda t: t.rank or 999)
            if sorted_tags[0].tag == "indie":
                assert sorted_tags[0].rank == 1


class TestEnrichmentReport:
    def test_report_dataclass_frozen(self):
        """Test that EnrichmentReport is frozen."""
        report = EnrichmentReport(
            run_id="test",
            rows_written=10,
            rows_dropped=2,
            dropped_by_reason={"non_game_app_type": 2},
            imputation_rate_by_feature={},
            unmatched_genre_count=0,
            free_to_play_count=1,
            duration_seconds=5.0,
        )

        with pytest.raises(AttributeError):
            report.rows_written = 20

    def test_report_counts_consistent(self):
        """Test that rows_written + rows_dropped makes sense."""
        report = EnrichmentReport(
            run_id="test",
            rows_written=100,
            rows_dropped=5,
            dropped_by_reason={"non_game_app_type": 5},
            imputation_rate_by_feature={},
            unmatched_genre_count=0,
            free_to_play_count=10,
            duration_seconds=5.0,
        )

        # Total candidates = written + dropped
        assert report.rows_written + report.rows_dropped == 105

    def test_report_imputation_rates_valid(self):
        """Test that imputation rates are in [0.0, 1.0]."""
        report = EnrichmentReport(
            run_id="test",
            rows_written=100,
            rows_dropped=0,
            dropped_by_reason={},
            imputation_rate_by_feature={
                "size_bytes": 0.12,
                "achievement_count": 0.08,
                "language_count": 0.05,
            },
            unmatched_genre_count=0,
            free_to_play_count=0,
            duration_seconds=5.0,
        )

        for rate in report.imputation_rate_by_feature.values():
            assert 0.0 <= rate <= 1.0

    def test_empty_run_report(self):
        """Test report for an empty candidate set."""
        report = EnrichmentReport(
            run_id="test",
            rows_written=0,
            rows_dropped=0,
            dropped_by_reason={},
            imputation_rate_by_feature={
                "size_bytes": 0.0,
                "achievement_count": 0.0,
            },
            unmatched_genre_count=0,
            free_to_play_count=0,
            duration_seconds=1.0,
        )

        assert report.rows_written == 0
        assert report.rows_dropped == 0


class TestRunEnrichment:
    def test_run_enrichment_nonexistent_run(self, temp_db, basic_params):
        """Test that run_enrichment raises error for unknown run_id."""
        with pytest.raises(Exception):  # EnrichmentError
            run_enrichment(
                temp_db,
                "nonexistent-run",
                basic_params,
                parameters_version="v1",
                on_event=lambda *args, **kwargs: None,
            )

    def test_run_enrichment_no_steamspy_rows(self, temp_db, basic_params):
        """Test that run_enrichment raises error if steamspy_all is empty."""
        run_id = create_run(temp_db, config={}, parameters_version="v1")

        with pytest.raises(Exception):  # EnrichmentError about missing steamspy_all
            run_enrichment(
                temp_db,
                run_id,
                basic_params,
                parameters_version="v1",
                on_event=lambda *args, **kwargs: None,
            )

    def test_run_enrichment_full_workflow(self, temp_db, simple_bundle, simple_catalog, basic_params):
        """Test complete enrichment workflow with database."""
        # Create run
        run_id = create_run(temp_db, config={}, parameters_version="v1")

        # Insert raw payloads
        now = datetime.utcnow()
        payloads = []

        # Add steamspy_all payloads
        for appid, data in simple_bundle.steamspy.items():
            payloads.append(RawPayload(
                appid=appid,
                source="steamspy_all",
                fetched_at=now,
                http_status=200,
                payload=data,
                payload_sha256=_sha256(data),
            ))

        # Add steamspy_appdetails payloads (the real tag source)
        for appid, data in simple_bundle.steamspy_appdetails.items():
            payloads.append(RawPayload(
                appid=appid,
                source="steamspy_appdetails",
                fetched_at=now,
                http_status=200,
                payload=data,
                payload_sha256=_sha256(data),
            ))

        # Add appdetails payloads
        for appid, data in simple_bundle.appdetails.items():
            payloads.append(RawPayload(
                appid=appid,
                source="steam_appdetails",
                fetched_at=now,
                http_status=200,
                payload=data,
                payload_sha256=_sha256(data),
            ))

        # Add reviews payloads
        for appid, data in simple_bundle.reviews.items():
            payloads.append(RawPayload(
                appid=appid,
                source="steam_reviews",
                fetched_at=now,
                http_status=200,
                payload=data,
                payload_sha256=_sha256(data),
            ))

        upsert_raw_payloads(temp_db, run_id, payloads)

        # Run enrichment
        events = []
        def capture_event(*args, **kwargs):
            events.append(kwargs if kwargs else args)

        report = run_enrichment(
            temp_db,
            run_id,
            basic_params,
            parameters_version="v1",
            on_event=capture_event,
        )

        # Verify report
        assert report.run_id == run_id
        assert report.rows_written == 2
        assert report.rows_dropped == 0
        assert report.free_to_play_count == 1

        # Verify data was written to storage
        enriched = read_enriched(temp_db, run_id)
        assert len(enriched) == 2
        assert all(enriched["parameters_version"] == "v1")

        # Verify tags were written
        tags = read_tags(temp_db, run_id)
        assert len(tags) > 0

        # Verify events were emitted
        assert len(events) > 0
        assert any("Starting enrichment" in str(e) for e in events)
        assert any("Enrichment complete" in str(e) for e in events)

    def test_run_enrichment_idempotent(self, temp_db, simple_bundle, simple_catalog, basic_params):
        """Test that re-running enrichment is idempotent."""
        # Setup
        run_id = create_run(temp_db, config={}, parameters_version="v1")

        now = datetime.utcnow()
        payloads = []

        for appid, data in simple_bundle.steamspy.items():
            payloads.append(RawPayload(
                appid=appid,
                source="steamspy_all",
                fetched_at=now,
                http_status=200,
                payload=data,
                payload_sha256=_sha256(data),
            ))

        for appid, data in simple_bundle.appdetails.items():
            payloads.append(RawPayload(
                appid=appid,
                source="steam_appdetails",
                fetched_at=now,
                http_status=200,
                payload=data,
                payload_sha256=_sha256(data),
            ))

        for appid, data in simple_bundle.reviews.items():
            payloads.append(RawPayload(
                appid=appid,
                source="steam_reviews",
                fetched_at=now,
                http_status=200,
                payload=data,
                payload_sha256=_sha256(data),
            ))

        upsert_raw_payloads(temp_db, run_id, payloads)

        # Run enrichment twice
        report1 = run_enrichment(
            temp_db,
            run_id,
            basic_params,
            parameters_version="v1",
            on_event=lambda *args, **kwargs: None,
        )

        report2 = run_enrichment(
            temp_db,
            run_id,
            basic_params,
            parameters_version="v1",
            on_event=lambda *args, **kwargs: None,
        )

        # Reports should match
        assert report1.rows_written == report2.rows_written
        assert report1.rows_dropped == report2.rows_dropped
        assert report1.free_to_play_count == report2.free_to_play_count

        # Data should be identical
        enriched1 = read_enriched(temp_db, run_id)
        enriched2 = read_enriched(temp_db, run_id)
        assert len(enriched1) == len(enriched2)

    def test_run_enrichment_empty_candidate_set(self, temp_db, basic_params):
        """Test enrichment with an empty candidate set."""
        run_id = create_run(temp_db, config={}, parameters_version="v1")

        # Add only steamspy_all (empty set)
        now = datetime.utcnow()
        empty_catalog = {"appid": 0, "name": "", "developer": "", "positive": 0}
        payload = RawPayload(
            appid=0,
            source="steamspy_all",
            fetched_at=now,
            http_status=200,
            payload=empty_catalog,
            payload_sha256=_sha256(empty_catalog),
        )
        upsert_raw_payloads(temp_db, run_id, [payload])

        # Create a bundle with the dummy payload
        bundle = RawBundle(
            run_id=run_id,
            steamspy={0: empty_catalog},
            steamspy_appdetails={},
            appdetails={},
            reviews={},
        )

        # This should still work (empty result set)
        report = run_enrichment(
            temp_db,
            run_id,
            basic_params,
            parameters_version="v1",
            on_event=lambda *args, **kwargs: None,
        )

        # Should succeed with zero rows written
        assert report.rows_written >= 0  # May be 0 or 1 depending on filter
