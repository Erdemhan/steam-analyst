"""Unit tests for enrichment.parsing module."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from steam_analyst.enrichment.errors import EnrichmentError
from steam_analyst.enrichment.parsing import (
    RawBundle,
    extract_tags,
    normalize_features,
    parse_raw_bundle,
)
from steam_analyst.storage import (
    create_run,
    get_connection,
    initialize_schema,
    upsert_raw_payloads,
)
from steam_analyst.storage.types import RawPayload, TagRow


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database with schema."""
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    initialize_schema(conn)
    yield conn
    conn.close()


def _sha256(obj):
    """Compute SHA256 of a JSON object."""
    import hashlib
    json_bytes = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(json_bytes).hexdigest()


class TestRawBundle:
    def test_bundle_dataclass_frozen(self):
        """Test that RawBundle is frozen (immutable)."""
        bundle = RawBundle(run_id="test", steamspy={}, steamspy_appdetails={}, appdetails={}, reviews={})
        with pytest.raises(AttributeError):
            bundle.run_id = "modified"

    def test_bundle_attributes(self):
        """Test RawBundle attributes are correctly stored."""
        steamspy_data = {1: {"name": "Test"}}
        appdetails_data = {1: {"success": True}}
        reviews_data = {1: {"success": 1}}

        bundle = RawBundle(
            run_id="test-123",
            steamspy=steamspy_data,
            steamspy_appdetails={},
            appdetails=appdetails_data,
            reviews=reviews_data,
        )

        assert bundle.run_id == "test-123"
        assert bundle.steamspy == steamspy_data
        assert bundle.appdetails == appdetails_data
        assert bundle.reviews == reviews_data


class TestParseRawBundle:
    def test_parse_raw_bundle_nonexistent_run(self, temp_db):
        """Test that unknown run_id raises EnrichmentError."""
        with pytest.raises(EnrichmentError, match="does not exist"):
            parse_raw_bundle(temp_db, "nonexistent-run-id")

    def test_parse_raw_bundle_empty_sources(self, temp_db):
        """Test parsing a run with no data yet."""
        run_id = create_run(temp_db, config={}, parameters_version="v1")

        bundle = parse_raw_bundle(temp_db, run_id)

        assert bundle.run_id == run_id
        assert bundle.steamspy == {}
        assert bundle.appdetails == {}
        assert bundle.reviews == {}

    def test_parse_raw_bundle_partial_sources(self, temp_db):
        """Test parsing a run with only some sources present."""
        run_id = create_run(temp_db, config={}, parameters_version="v1")

        # Add only steamspy_all
        now = datetime.utcnow()
        steamspy_data = {"100": {"appid": 100, "name": "Test"}}
        payload = RawPayload(
            appid=100,
            source="steamspy_all",
            fetched_at=now,
            http_status=200,
            payload=steamspy_data,
            payload_sha256=_sha256(steamspy_data),
        )
        upsert_raw_payloads(temp_db, run_id, [payload])

        bundle = parse_raw_bundle(temp_db, run_id)

        assert 100 in bundle.steamspy
        assert bundle.appdetails == {}
        assert bundle.reviews == {}

    def test_parse_raw_bundle_multiple_appids(self, temp_db):
        """Test parsing multiple appids across sources."""
        run_id = create_run(temp_db, config={}, parameters_version="v1")

        now = datetime.utcnow()
        steamspy_all = {
            "100": {"appid": 100, "name": "Game 1"},
            "101": {"appid": 101, "name": "Game 2"},
        }
        appdetails = {
            "100": {"success": True, "data": {"type": "game"}},
        }
        reviews = {
            "100": {"success": 1},
        }

        payloads = [
            RawPayload(100, "steamspy_all", now, 200, steamspy_all, _sha256(steamspy_all)),
            RawPayload(101, "steamspy_all", now, 200, steamspy_all, _sha256(steamspy_all)),
            RawPayload(100, "steam_appdetails", now, 200, appdetails, _sha256(appdetails)),
            RawPayload(100, "steam_reviews", now, 200, reviews, _sha256(reviews)),
        ]
        upsert_raw_payloads(temp_db, run_id, payloads)

        bundle = parse_raw_bundle(temp_db, run_id)

        assert set(bundle.steamspy.keys()) == {100, 101}
        assert set(bundle.appdetails.keys()) == {100}
        assert set(bundle.reviews.keys()) == {100}


class TestNormalizeFeatures:
    def test_normalize_features_success_path(self):
        """Test normalizing a fully successful bundle."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test Game",
                "developer": "Test Dev",
                "publisher": "Test Pub",
                "positive": 1000,
                "negative": 100,
                "owners_low": 10000,
                "owners_high": 50000,
                "tags": {"action": 100},
            }
        }
        appdetails_data = {
            "100": {
                "success": True,
                "data": {
                    "type": "game",
                    "name": "Test Game",
                    "is_free": False,
                    "developers": ["Test Dev"],
                    "publishers": ["Test Pub"],
                    "price_overview": {"currency": "USD", "final": 1999},
                    "platforms": {"windows": True, "mac": True, "linux": False},
                    "genres": [{"description": "Action"}],
                    "categories": [{"description": "Single-player"}],
                    "achievements": {"total": 50},
                    "supported_languages": "English, French",
                    "dlc": [],
                    "release_date": {"date": "01 Jan, 2023"},
                    "size_bytes": 5000000000,
                    "is_early_access": False,
                },
            }
        }
        reviews_data = {
            "100": {
                "success": 1,
                "query_summary": {
                    "total_reviews": 1100,
                    "total_positive": 990,
                    "review_score": 8,
                },
            }
        }

        steamspy_appdetails_data = {
            "100": {
                "appid": 100,
                "tags": {"action": 100},
            }
        }

        bundle = RawBundle(
            "test", steamspy_data, steamspy_appdetails_data, appdetails_data, reviews_data
        )
        df = normalize_features(bundle)

        assert len(df) == 1
        assert df.loc[100, "name"] == "Test Game"
        assert df.loc[100, "price_usd"] == 19.99
        assert df.loc[100, "is_free"] == False
        assert df.loc[100, "review_count"] == 1100
        assert df.loc[100, "review_count_source"] == "steam_reviews"
        assert abs(df.loc[100, "review_positive_pct"] - 0.90) < 0.001
        assert df.loc[100, "achievement_count"] == 50
        assert df.loc[100, "platform_count"] == 2
        assert df.loc[100, "language_count"] == 2
        assert df.loc[100, "dlc_count"] == 0
        assert df.loc[100, "is_game"] == True

    def test_normalize_features_appdetails_failure(self):
        """Test normalizing with appdetails fetch failure."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test Game",
                "developer": "Test Dev",
                "positive": 1000,
                "negative": 100,
            }
        }
        appdetails_data = {
            "100": {"success": False}
        }
        reviews_data = {}

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        assert len(df) == 1
        assert df.loc[100, "is_game"] == False
        assert pd.isna(df.loc[100, "price_usd"])
        assert df.loc[100, "review_count_source"] == "steamspy_fallback"

    def test_normalize_features_review_count_fallback(self):
        """Test that review_count falls back to SteamSpy when reviews missing."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test",
                "positive": 500,
                "negative": 50,
                "owners_low": 1000,
                "owners_high": 5000,
            }
        }
        appdetails_data = {
            "100": {
                "success": True,
                "data": {"type": "game", "developers": ["Dev"]},
            }
        }
        reviews_data = {}  # No reviews data

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        assert df.loc[100, "review_count"] == 550  # positive + negative
        assert df.loc[100, "review_count_source"] == "steamspy_fallback"

    def test_normalize_features_review_pct_normalization(self):
        """Positive fraction comes from total_positive/total_reviews, never from the 1-9 review_score."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test",
                "positive": 1000,
                "negative": 100,
                "owners_low": 1000,
                "owners_high": 5000,
            }
        }
        appdetails_data = {}
        reviews_data = {
            "100": {
                "success": 1,
                "query_summary": {
                    "total_reviews": 1100,
                    "total_positive": 957,
                    "review_score": 8,  # Steam's 1-9 categorical rating, not a percentage
                },
            }
        }

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        # 957 / 1100 = 0.87
        assert abs(df.loc[100, "review_positive_pct"] - 0.87) < 0.001

    def test_normalize_features_empty_tags_list(self):
        """Test handling tags as empty list."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test",
                "positive": 100,
                "negative": 10,
                "tags": [],  # Empty tags list
            }
        }
        appdetails_data = {}
        reviews_data = {}

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        assert len(df) == 1
        assert df.loc[100, "name"] == "Test"

    def test_normalize_features_genres_and_categories_json(self):
        """Test that genres and categories are properly encoded as JSON."""
        steamspy_data = {
            "100": {"appid": 100, "name": "Test", "positive": 100, "negative": 10}
        }
        appdetails_data = {
            "100": {
                "success": True,
                "data": {
                    "type": "game",
                    "genres": [
                        {"description": "Action"},
                        {"description": "Adventure"},
                    ],
                    "categories": [
                        {"description": "Single-player"},
                        {"description": "Steam Achievements"},
                    ],
                },
            }
        }
        reviews_data = {}

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        genres = json.loads(df.loc[100, "genres_json"])
        categories = json.loads(df.loc[100, "categories_json"])

        assert genres == ["Action", "Adventure"]
        assert categories == ["Single-player", "Steam Achievements"]

    def test_normalize_features_missing_genres_empty_json(self):
        """Test that missing genres/categories produce empty JSON arrays."""
        steamspy_data = {
            "100": {"appid": 100, "name": "Test", "positive": 100, "negative": 10}
        }
        appdetails_data = {
            "100": {
                "success": True,
                "data": {"type": "game"},
            }
        }
        reviews_data = {}

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        assert df.loc[100, "genres_json"] == "[]"
        assert df.loc[100, "categories_json"] == "[]"

    def test_normalize_features_missing_fields_tracked(self):
        """Test that missing optional fields are tracked in missing_fields_json."""
        steamspy_data = {
            "100": {"appid": 100, "name": "Test", "positive": 100, "negative": 10}
        }
        appdetails_data = {
            "100": {
                "success": True,
                "data": {
                    "type": "game",
                    # No size_bytes, no achievements, no languages, no platforms
                },
            }
        }
        reviews_data = {}

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        missing_fields = json.loads(df.loc[100, "missing_fields_json"])
        assert "size_bytes" in missing_fields
        assert "achievement_count" in missing_fields

    def test_normalize_features_non_game_app_type(self):
        """Test that non-game app_type is recorded as is_game=False."""
        steamspy_data = {
            "100": {"appid": 100, "name": "Test", "positive": 100, "negative": 10}
        }
        appdetails_data = {
            "100": {
                "success": True,
                "data": {
                    "type": "dlc",  # Not a game
                    "name": "Test DLC",
                },
            }
        }
        reviews_data = {}

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        assert df.loc[100, "is_game"] == False

    def test_normalize_features_multiple_appids(self):
        """Test normalizing multiple appids."""
        steamspy_data = {
            "100": {"appid": 100, "name": "Game 1", "positive": 100, "negative": 10},
            "101": {"appid": 101, "name": "Game 2", "positive": 200, "negative": 20},
        }
        appdetails_data = {}
        reviews_data = {}

        bundle = RawBundle("test", steamspy_data, {}, appdetails_data, reviews_data)
        df = normalize_features(bundle)

        assert len(df) == 2
        assert set(df.index) == {100, 101}
        assert df.loc[100, "name"] == "Game 1"
        assert df.loc[101, "name"] == "Game 2"


class TestExtractTags:
    def test_extract_tags_respects_max_per_game(self):
        """Test that max_tags_per_game limits the output."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test",
                "tags": {
                    "action": 100,
                    "adventure": 95,
                    "indie": 90,
                    "rpg": 85,
                    "puzzle": 80,
                },
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=3, min_votes=0)

        assert len(tags) == 3
        # Should be top 3 by votes
        tag_names = [t.tag for t in tags]
        assert "action" in tag_names
        assert "adventure" in tag_names
        assert "indie" in tag_names

    def test_extract_tags_drops_below_min_votes(self):
        """Test that tags below min_votes are excluded."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test",
                "tags": {
                    "action": 100,
                    "adventure": 50,
                    "rare": 3,
                },
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=5)

        assert len(tags) == 2
        tag_names = [t.tag for t in tags]
        assert "rare" not in tag_names

    def test_extract_tags_empty_tags_list(self):
        """Test that empty tags list produces no output."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test",
                "tags": [],
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=0)

        assert len(tags) == 0

    def test_extract_tags_no_tags_field(self):
        """Test handling of apps with no tags field at all."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "name": "Test",
                # No tags field
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=0)

        assert len(tags) == 0

    def test_extract_tags_rank_ordering(self):
        """Test that ranks are correctly assigned 1-indexed."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "tags": {
                    "action": 100,
                    "adventure": 95,
                    "indie": 90,
                },
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=0)

        assert len(tags) == 3
        ranks = [t.rank for t in tags]
        assert ranks == [1, 2, 3]

    def test_extract_tags_tie_break_alphabetical(self):
        """Test that tags with equal votes are ranked alphabetically."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "tags": {
                    "zebra": 100,
                    "apple": 100,
                    "banana": 100,
                },
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=0)

        assert len(tags) == 3
        tag_names = [t.tag for t in tags]
        # Should be alphabetically sorted for ties
        assert tag_names == ["apple", "banana", "zebra"]

    def test_extract_tags_multiple_appids(self):
        """Test extracting tags from multiple apps."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "tags": {"action": 100, "adventure": 95},
            },
            "101": {
                "appid": 101,
                "tags": {"puzzle": 80, "indie": 75},
            },
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=0)

        assert len(tags) == 4
        tags_by_appid = {}
        for tag in tags:
            if tag.appid not in tags_by_appid:
                tags_by_appid[tag.appid] = []
            tags_by_appid[tag.appid].append(tag)

        assert len(tags_by_appid[100]) == 2
        assert len(tags_by_appid[101]) == 2

    def test_extract_tags_rank_contiguity(self):
        """Test that ranks are contiguous and unique within each app."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "tags": {
                    "a": 100,
                    "b": 50,
                    "c": 25,
                },
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=0)

        ranks = sorted([t.rank for t in tags])
        assert ranks == [1, 2, 3]  # Contiguous

    def test_extract_tags_votes_preserved(self):
        """Test that vote counts are preserved in TagRow."""
        steamspy_data = {
            "100": {
                "appid": 100,
                "tags": {
                    "action": 1234,
                    "adventure": 567,
                },
            }
        }
        bundle = RawBundle("test", {}, steamspy_data, {}, {})

        tags = extract_tags(bundle, max_tags_per_game=10, min_votes=0)

        tag_dict = {t.tag: t.votes for t in tags}
        assert tag_dict["action"] == 1234
        assert tag_dict["adventure"] == 567
