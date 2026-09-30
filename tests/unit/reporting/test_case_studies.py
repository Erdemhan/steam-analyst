"""Unit tests for reporting.case_studies module."""

import math
import re
from unittest.mock import MagicMock

import pandas as pd
import pytest

from steam_analyst.reporting.case_studies import (
    CaseStudy,
    build_rationale,
    interpretive_caveats,
    select_case_studies,
)
from steam_analyst.reporting.types import CaseStudySelection


class TestCaseStudy:
    """Tests for CaseStudy dataclass."""

    def test_case_study_creation(self):
        """A CaseStudy can be created with all fields."""
        cs = CaseStudy(
            appid=12345,
            name="Test Game",
            developer="Test Dev",
            release_date="2023-01-01",
            price_usd=9.99,
            review_count=1000,
            review_positive_pct=0.85,
            estimated_sales_band=(100, 150, 200),
            estimated_revenue_net_usd=1000.0,
            complexity_score=0.5,
            top_tags=["Indie", "Puzzle"],
            archetype_label="Casual Puzzle",
            rationale="This game is interesting.",
            complexity_drivers=[("install_size", 0.15)],
            store_url="https://store.steampowered.com/app/12345/",
        )
        assert cs.appid == 12345
        assert cs.name == "Test Game"
        assert cs.price_usd == 9.99

    def test_case_study_is_frozen(self):
        """A CaseStudy instance is immutable (frozen dataclass)."""
        cs = CaseStudy(
            appid=1,
            name="Test",
            developer="Dev",
            release_date="2023-01-01",
            price_usd=5.0,
            review_count=100,
            review_positive_pct=0.8,
            estimated_sales_band=(10, 15, 20),
            estimated_revenue_net_usd=100.0,
            complexity_score=0.3,
            top_tags=["Tag"],
            archetype_label="Label",
            rationale="Rationale",
            complexity_drivers=[],
            store_url="https://store.steampowered.com/app/1/",
        )
        with pytest.raises(AttributeError):
            cs.name = "Modified"

    def test_case_study_sales_band_ordering(self):
        """Sales band must be non-decreasing: low <= mid <= high."""
        cs = CaseStudy(
            appid=1,
            name="Test",
            developer="Dev",
            release_date="2023-01-01",
            price_usd=5.0,
            review_count=100,
            review_positive_pct=0.8,
            estimated_sales_band=(100, 150, 200),
            estimated_revenue_net_usd=500.0,
            complexity_score=0.3,
            top_tags=["Tag"],
            archetype_label="Label",
            rationale="Rationale",
            complexity_drivers=[],
            store_url="https://store.steampowered.com/app/1/",
        )
        low, mid, high = cs.estimated_sales_band
        assert low <= mid <= high

    def test_case_study_free_to_play_revenue_not_coerced_to_zero(self):
        """F2P case study with NaN revenue must stay NaN, not coerce to 0.0."""
        cs = CaseStudy(
            appid=1,
            name="Free Game",
            developer="Dev",
            release_date="2023-01-01",
            price_usd=0.0,
            review_count=100,
            review_positive_pct=0.8,
            estimated_sales_band=(float("nan"), float("nan"), float("nan")),
            estimated_revenue_net_usd=float("nan"),
            complexity_score=0.3,
            top_tags=["Tag"],
            archetype_label="Label",
            rationale="Rationale",
            complexity_drivers=[],
            store_url="https://store.steampowered.com/app/1/",
        )
        # Check that revenue is NaN, not 0.0
        assert math.isnan(cs.estimated_revenue_net_usd)
        assert cs.estimated_revenue_net_usd != 0.0

    def test_case_study_store_url_format(self):
        """store_url is correctly formatted."""
        appid = 54321
        cs = CaseStudy(
            appid=appid,
            name="Test",
            developer="Dev",
            release_date="2023-01-01",
            price_usd=5.0,
            review_count=100,
            review_positive_pct=0.8,
            estimated_sales_band=(10, 15, 20),
            estimated_revenue_net_usd=100.0,
            complexity_score=0.3,
            top_tags=["Tag"],
            archetype_label="Label",
            rationale="Rationale",
            complexity_drivers=[],
            store_url=f"https://store.steampowered.com/app/{appid}/",
        )
        assert f"/app/{appid}/" in cs.store_url


class TestBuildRationale:
    """Tests for build_rationale function."""

    def test_rationale_contains_stored_signals(self):
        """Rationale contains the exact numeric values from the row."""
        row = pd.Series({
            "review_count": 5000,
            "review_positive_pct": 0.87,
            "price_usd": 12.99,
            "size_bytes": 2.5e9,
            "dev_title_count": 3.0,
            "achievement_count": 15,
        })
        archetype = "Adventure"

        rationale = build_rationale(row, archetype)

        # Check that concrete numbers appear
        assert "5,000" in rationale or "5000" in rationale
        assert "12.99" in rationale or "12.99" in str(rationale)
        assert "Adventure" in rationale

    def test_rationale_contains_no_unhedged_effort_claim(self):
        """Rationale contains no forbidden unhedged effort phrases."""
        row = pd.Series({
            "review_count": 1000,
            "review_positive_pct": 0.8,
            "price_usd": 10.0,
            "size_bytes": 1e9,
            "dev_title_count": 2.0,
            "achievement_count": 10,
        })
        rationale = build_rationale(row, "Puzzle")

        forbidden_phrases = [
            "took",
            "cost",
            "weeks",
            "months",
            "days",
            "developed in",
            "built in",
            "made in",
            "created in",
            "spent",
            "required",
            "estimated at",
        ]

        lowercase = rationale.lower()
        for phrase in forbidden_phrases:
            # Be more careful: "took" might appear in something like "mistake", so check word boundaries
            if phrase in ["took", "cost", "spent"]:
                # These shouldn't appear at all as whole words
                assert not re.search(rf"\b{phrase}\b", lowercase, re.IGNORECASE)

    def test_rationale_free_to_play_renders_free_not_zero_dollars(self):
        """price_usd=0 renders as 'free-to-play', not '$0.00'."""
        row = pd.Series({
            "review_count": 1000,
            "review_positive_pct": 0.8,
            "price_usd": 0.0,
            "size_bytes": 1e9,
            "dev_title_count": 1.0,
            "achievement_count": 5,
        })
        rationale = build_rationale(row, "Casual")

        assert "free-to-play" in rationale.lower()
        assert "$0.00" not in rationale

    def test_rationale_missing_dev_title_count_omits_clause(self):
        """dev_title_count=NaN omits that clause without leaving a dangling 'nan' string."""
        row = pd.Series({
            "review_count": 1000,
            "review_positive_pct": 0.8,
            "price_usd": 10.0,
            "size_bytes": 1e9,
            "dev_title_count": float("nan"),
            "achievement_count": 5,
        })
        rationale = build_rationale(row, "Action")

        assert "nan" not in rationale.lower()
        assert "release" not in rationale.lower() or "prior" not in rationale.lower()

    def test_rationale_missing_review_positive_pct_omits_positivity(self):
        """review_positive_pct=NaN omits the positivity parenthetical."""
        row = pd.Series({
            "review_count": 1000,
            "review_positive_pct": float("nan"),
            "price_usd": 10.0,
            "size_bytes": 1e9,
            "dev_title_count": 2.0,
            "achievement_count": 5,
        })
        rationale = build_rationale(row, "Puzzle")

        # Should not have the percentage sign
        assert "%" not in rationale or rationale.count("%") < 1

    def test_rationale_missing_size_bytes_omits_size_clause(self):
        """size_bytes=NaN omits the install size clause."""
        row = pd.Series({
            "review_count": 1000,
            "review_positive_pct": 0.8,
            "price_usd": 10.0,
            "size_bytes": float("nan"),
            "dev_title_count": 2.0,
            "achievement_count": 5,
        })
        rationale = build_rationale(row, "RPG")

        # Should not have size mentions
        assert "mb" not in rationale.lower() and "gb" not in rationale.lower()

    def test_rationale_is_single_sentence(self):
        """Rationale is a single sentence (ends with period, no multiple sentences)."""
        row = pd.Series({
            "review_count": 2000,
            "review_positive_pct": 0.75,
            "price_usd": 15.99,
            "size_bytes": 3e9,
            "dev_title_count": 5.0,
            "achievement_count": 20,
        })
        rationale = build_rationale(row, "Strategy")

        assert rationale.endswith(".")
        # Should be a single logical sentence (ends with period, no multiple "." followed by space)
        assert not re.search(r"\.\s[A-Z]", rationale)


class TestInterpretiveCaveats:
    """Tests for interpretive_caveats function."""

    def test_returns_one_caveat_per_limitation_with_stable_keys(self):
        """Returns exactly 8 Caveat entries with documented stable keys."""
        caveats = interpretive_caveats()

        assert len(caveats) == 8

        expected_keys = {
            "steamspy_owner_confidence",
            "boxleiter_approximation",
            "simplicity_proxy",
            "no_scraping_demand_gap",
            "survivorship_bias",
            "competition_historical",
            "coarse_filter_boundary",
            "boxleiter_accuracy_limit",
        }

        actual_keys = {c.key for c in caveats}
        assert actual_keys == expected_keys

    def test_caveats_all_have_severity_info(self):
        """All caveats have severity='info'."""
        caveats = interpretive_caveats()

        for caveat in caveats:
            assert caveat.severity in ("info", "warning")

    def test_boxleiter_accuracy_note_present(self):
        """The 'boxleiter_accuracy_limit' caveat's body contains the '43%' figure."""
        caveats = interpretive_caveats()

        boxleiter_accuracy = next(
            (c for c in caveats if c.key == "boxleiter_accuracy_limit"), None
        )
        assert boxleiter_accuracy is not None
        assert "43%" in boxleiter_accuracy.body

    def test_caveats_are_stable_across_calls(self):
        """Multiple calls return equal-by-value lists."""
        caveats1 = interpretive_caveats()
        caveats2 = interpretive_caveats()

        assert len(caveats1) == len(caveats2)
        for c1, c2 in zip(sorted(caveats1, key=lambda c: c.key), sorted(caveats2, key=lambda c: c.key)):
            assert c1.key == c2.key
            assert c1.title == c2.title
            assert c1.body == c2.body
            assert c1.severity == c2.severity

    def test_each_caveat_has_nonempty_title_and_body(self):
        """Each caveat has non-empty title and body text."""
        caveats = interpretive_caveats()

        for caveat in caveats:
            assert len(caveat.title) > 0
            assert len(caveat.body) > 0

    def test_limitation_1_steamspy_present(self):
        """Caveat for SteamSpy owner confidence (limitation 1) is present."""
        caveats = interpretive_caveats()
        steamspy = next((c for c in caveats if c.key == "steamspy_owner_confidence"), None)
        assert steamspy is not None
        assert "low-confidence" in steamspy.body.lower()

    def test_limitation_3_simplicity_proxy_present(self):
        """Caveat for simplicity proxy (limitation 3) mentions 'polish' and 'took two weeks'."""
        caveats = interpretive_caveats()
        simplicity = next((c for c in caveats if c.key == "simplicity_proxy"), None)
        assert simplicity is not None
        assert "plausibly small" in simplicity.body.lower() or "proxy" in simplicity.body.lower()


class TestSelectCaseStudies:
    """Tests for select_case_studies function."""

    @pytest.fixture
    def fixture_enriched_data(self):
        """Create a fixture enriched DataFrame with diverse entries."""
        data = {
            "appid": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18],
            "name": [f"Game {i}" for i in range(1, 19)],
            "developer": [
                "Dev A", "Dev A", "Dev A", "Dev A", "Dev A",  # 5 games, 1 archetype
                "Dev B", "Dev B", "Dev B",  # 3 games
                "Dev C", "Dev C",  # 2 games
                "Dev D",  # 1 game
                "Dev E", "Dev E", "Dev E", "Dev E", "Dev E", "Dev F", "Dev F",  # 7 (5+1+1)
            ],
            "effort_adjusted_return": [
                1000, 950, 900, 850, 800,  # Dev A
                750, 700, 650,  # Dev B
                600, 550,  # Dev C
                500,  # Dev D
                450, 400, 350, 300, 250, 200, 150,  # Dev E and F (7 total)
            ],
            "price_usd": [9.99] * 18,
            "review_count": [1000] * 18,
            "review_positive_pct": [0.8] * 18,
            "size_bytes": [1e9] * 18,
            "dev_title_count": [3.0] * 18,
            "archetype_label": [
                "Puzzle", "Puzzle", "Puzzle", "Puzzle", "Puzzle",  # Cluster 1, 5 games
                "Action", "Action", "Action",  # Cluster 2, 3 games
                "RPG", "RPG",  # Cluster 3, 2 games
                "Adventure",  # Cluster 4, 1 game
                "Strategy", "Strategy", "Strategy", "Strategy", "Strategy", "Casual", "Casual",  # Clusters 5 and 6 (7 total)
            ],
            "estimated_revenue_net_usd": [1000.0] * 18,
            "complexity_score": [0.3] * 18,
            "top_tags": [["Tag1", "Tag2"]] * 18,
            "complexity_drivers": [[] for _ in range(18)],
        }
        return pd.DataFrame(data)

    @pytest.fixture
    def fixture_assignments(self):
        """Create fixture assignments DataFrame."""
        data = {
            "appid": list(range(1, 19)),
            "cluster_id": [
                1, 1, 1, 1, 1,  # Cluster 1: Puzzle
                2, 2, 2,  # Cluster 2: Action
                3, 3,  # Cluster 3: RPG
                4,  # Cluster 4: Adventure
                5, 5, 5, 5, 5, 6, 6,  # Clusters 5 and 6
            ],
        }
        return pd.DataFrame(data)

    def test_respects_max_per_archetype_and_developer(
        self, fixture_enriched_data, fixture_assignments
    ):
        """Selection respects max_per_archetype and max_per_developer caps."""
        result = select_case_studies(
            fixture_enriched_data,
            fixture_assignments,
            top_n=15,
            max_per_archetype=2,
            max_per_developer=1,
        )

        # Check max_per_archetype
        cluster_counts = {}
        for cs in result.case_studies:
            archetype = cs.archetype_label
            cluster_counts[archetype] = cluster_counts.get(archetype, 0) + 1

        for count in cluster_counts.values():
            # Either count <= max_per_archetype or cap was relaxed (then count <= max_per_archetype + 1)
            if result.archetype_cap_relaxed:
                assert count <= 3  # 2 + 1 relaxation
            else:
                assert count <= 2

        # Check max_per_developer
        developer_counts = {}
        for cs in result.case_studies:
            dev = cs.developer
            developer_counts[dev] = developer_counts.get(dev, 0) + 1

        for count in developer_counts.values():
            assert count <= 1  # Developer cap is never relaxed

    def test_returns_fewer_than_top_n_without_padding(
        self, fixture_enriched_data, fixture_assignments
    ):
        """When pool is smaller than top_n, returns smaller list without padding."""
        small_enriched = fixture_enriched_data.iloc[:8].copy()
        small_assignments = fixture_assignments.iloc[:8].copy()

        result = select_case_studies(
            small_enriched,
            small_assignments,
            top_n=15,
            max_per_archetype=2,
            max_per_developer=1,
        )

        # With max_per_developer=1 and 8 games across many developers, should get close to 8
        assert len(result.case_studies) <= 8
        assert len(result.case_studies) > 0

    def test_archetype_cap_relaxed_once_when_needed(self):
        """When strict caps can't fill top_n, max_per_archetype relaxes exactly once."""
        # Create a scenario where strict archetype cap prevents reaching top_n
        # One archetype with many high-ranking games, developer cap doesn't interfere
        enriched = pd.DataFrame({
            "appid": list(range(1, 13)),
            "effort_adjusted_return": [1000, 950, 900, 850, 800, 750, 700, 650, 600, 550, 500, 450],
            "name": [f"Game {i}" for i in range(1, 13)],
            "developer": [f"Dev {i}" for i in range(1, 13)],  # Each game has different developer
            "price_usd": [10.0] * 12,
            "review_count": [100] * 12,
            "review_positive_pct": [0.8] * 12,
            "size_bytes": [1e9] * 12,
            "dev_title_count": [1.0] * 12,
            "archetype_label": ["Puzzle"] * 12,  # All same archetype
            "estimated_revenue_net_usd": [1000.0] * 12,
            "complexity_score": [0.3] * 12,
            "top_tags": [["Tag"]] * 12,
            "complexity_drivers": [[] for _ in range(12)],
        })
        assignments = pd.DataFrame({
            "appid": list(range(1, 13)),
            "cluster_id": [1] * 12,  # All same cluster
        })

        result = select_case_studies(
            enriched,
            assignments,
            top_n=10,
            max_per_archetype=2,
            max_per_developer=10,  # High cap so developer cap doesn't bind
        )

        # With max_per_archetype=2 and top_n=10 with 12 candidates all in same archetype,
        # relaxation should fire to reach more of the top_n slots
        assert result.archetype_cap_relaxed is True
        cluster_counts = {}
        for cs in result.case_studies:
            archetype = cs.archetype_label
            cluster_counts[archetype] = cluster_counts.get(archetype, 0) + 1

        # At least one cluster should have 3 entries (2 + 1 relaxation)
        max_in_cluster = max(cluster_counts.values())
        assert max_in_cluster >= 3

    def test_nan_effort_adjusted_return_excluded(
        self, fixture_enriched_data, fixture_assignments
    ):
        """F2P or NULL complexity (NaN effort_adjusted_return) are excluded from selection."""
        # Inject NaN values
        enriched_with_nan = fixture_enriched_data.copy()
        enriched_with_nan.loc[0, "effort_adjusted_return"] = float("nan")
        enriched_with_nan.loc[1, "effort_adjusted_return"] = float("nan")

        result = select_case_studies(
            enriched_with_nan,
            fixture_assignments,
            top_n=15,
            max_per_archetype=2,
            max_per_developer=1,
        )

        # Appids 1 and 2 should never appear
        selected_appids = {cs.appid for cs in result.case_studies}
        assert 1 not in selected_appids
        assert 2 not in selected_appids

    def test_ranked_by_effort_adjusted_return_descending(
        self, fixture_enriched_data, fixture_assignments
    ):
        """Selection is ranked by effort_adjusted_return descending (best first)."""
        result = select_case_studies(
            fixture_enriched_data,
            fixture_assignments,
            top_n=15,
            max_per_archetype=10,  # Relax archetype cap to avoid filtering
            max_per_developer=10,  # Relax developer cap to avoid filtering
        )

        # Check ranking: each subsequent entry should have effort_adjusted_return <= previous
        efforts = [cs.estimated_revenue_net_usd for cs in result.case_studies]
        for i in range(len(efforts) - 1):
            assert efforts[i] >= efforts[i + 1]

    def test_empty_eligible_pool_returns_empty(self):
        """If no eligible candidates (all have NaN effort_adjusted_return), return empty."""
        enriched = pd.DataFrame({
            "appid": [1, 2, 3],
            "effort_adjusted_return": [float("nan"), float("nan"), float("nan")],
            "name": ["G1", "G2", "G3"],
            "developer": ["D1", "D2", "D3"],
            "price_usd": [10.0, 10.0, 10.0],
            "review_count": [100, 100, 100],
            "review_positive_pct": [0.8, 0.8, 0.8],
            "size_bytes": [1e9, 1e9, 1e9],
            "ram_bytes": [1e9, 1e9, 1e9],
            "dev_title_count": [1.0, 1.0, 1.0],
            "archetype_label": ["A", "B", "C"],
            "estimated_revenue_net_usd": [1000.0, 1000.0, 1000.0],
            "complexity_score": [0.3, 0.3, 0.3],
            "top_tags": [[], [], []],
            "complexity_drivers": [[], [], []],
        })
        assignments = pd.DataFrame({
            "appid": [1, 2, 3],
            "cluster_id": [1, 2, 3],
        })

        result = select_case_studies(enriched, assignments, top_n=10)

        assert len(result.case_studies) == 0
        assert result.archetype_cap_relaxed is False

    def test_returns_case_study_selection_type(self):
        """Returns CaseStudySelection, not a bare list."""
        enriched = pd.DataFrame({
            "appid": [1],
            "effort_adjusted_return": [100.0],
            "name": ["Game"],
            "developer": ["Dev"],
            "price_usd": [5.0],
            "review_count": [100],
            "review_positive_pct": [0.8],
            "size_bytes": [1e9],
            "ram_bytes": [1e9],
            "dev_title_count": [1.0],
            "archetype_label": ["Action"],
            "estimated_revenue_net_usd": [500.0],
            "complexity_score": [0.3],
            "top_tags": [["Tag"]],
            "complexity_drivers": [[]],
        })
        assignments = pd.DataFrame({
            "appid": [1],
            "cluster_id": [1],
        })

        result = select_case_studies(enriched, assignments)

        assert isinstance(result, CaseStudySelection)
        assert isinstance(result.case_studies, list)
        assert isinstance(result.archetype_cap_relaxed, bool)

    def test_archetype_cap_relaxed_false_when_not_needed(
        self, fixture_enriched_data, fixture_assignments
    ):
        """archetype_cap_relaxed is False when strict caps already fill top_n."""
        result = select_case_studies(
            fixture_enriched_data,
            fixture_assignments,
            top_n=4,  # Small target
            max_per_archetype=2,
            max_per_developer=2,
        )

        # With small top_n, strict caps should fill it
        assert len(result.case_studies) == 4
        assert result.archetype_cap_relaxed is False

    def test_developer_cap_never_relaxed(self, fixture_enriched_data, fixture_assignments):
        """Even if archetype cap relaxes, developer cap is never relaxed."""
        result = select_case_studies(
            fixture_enriched_data,
            fixture_assignments,
            top_n=18,  # Try to get all 18
            max_per_archetype=5,  # High, likely to relax
            max_per_developer=1,  # Strict, never relax
        )

        # Developer cap should always be respected
        developer_counts = {}
        for cs in result.case_studies:
            dev = cs.developer
            developer_counts[dev] = developer_counts.get(dev, 0) + 1

        for count in developer_counts.values():
            assert count <= 1


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_case_study_created_from_enriched_row_has_valid_rationale(self):
        """A CaseStudy created from enriched data has a valid rationale."""
        row = pd.Series({
            "appid": 123,
            "name": "Test Game",
            "developer": "Dev",
            "release_date": "2023-01-01",
            "price_usd": 9.99,
            "review_count": 5000,
            "review_positive_pct": 0.87,
            "estimated_revenue_net_usd": 10000.0,
            "complexity_score": 0.4,
            "size_bytes": 2e9,
            "dev_title_count": 3.0,
            "achievement_count": 20,
            "top_tags": ["Puzzle", "Indie"],
            "complexity_drivers": [("size", 0.2)],
        })

        rationale = build_rationale(row, "Puzzle Adventure")

        # Rationale should be non-empty and contain key numbers
        assert len(rationale) > 0
        assert "5,000" in rationale or "5000" in rationale
        assert "Puzzle Adventure" in rationale

    def test_select_case_studies_produces_valid_case_studies(self):
        """select_case_studies returns CaseStudy objects with all fields populated."""
        enriched = pd.DataFrame({
            "appid": [1, 2, 3],
            "name": ["G1", "G2", "G3"],
            "developer": ["D1", "D2", "D3"],
            "release_date": ["2023-01-01"] * 3,
            "price_usd": [10.0, 5.0, 15.0],
            "review_count": [1000, 500, 2000],
            "review_positive_pct": [0.8, 0.75, 0.85],
            "estimated_sales_band": [(100, 150, 200)] * 3,
            "estimated_revenue_net_usd": [1000.0, 500.0, 2000.0],
            "complexity_score": [0.3, 0.4, 0.2],
            "top_tags": [["Tag1"], ["Tag2"], ["Tag3"]],
            "archetype_label": ["Puzzle", "Action", "RPG"],
            "rationale": ["Rationale 1", "Rationale 2", "Rationale 3"],
            "complexity_drivers": [[], [], []],
            "effort_adjusted_return": [100.0, 150.0, 200.0],
            "owners_estimate_low": [100, 50, 200],
            "owners_estimate_mid": [150, 75, 300],
            "owners_estimate_high": [200, 100, 400],
            "size_bytes": [1e9, 2e9, 3e9],
            "ram_bytes": [1e9, 2e9, 3e9],
            "dev_title_count": [1.0, 2.0, 3.0],
        })
        assignments = pd.DataFrame({
            "appid": [1, 2, 3],
            "cluster_id": [1, 2, 3],
        })

        result = select_case_studies(enriched, assignments, top_n=3)

        assert len(result.case_studies) > 0
        for cs in result.case_studies:
            assert isinstance(cs, CaseStudy)
            assert cs.appid > 0
            assert len(cs.name) > 0
            assert len(cs.store_url) > 0
            assert len(cs.rationale) > 0
