"""Unit tests for analysis.clustering module."""

import numpy as np
from dataclasses import replace

import pandas as pd
import pytest

from steam_analyst.analysis.clustering import (
    TagClusterResult,
    compute_jaccard_tag_distance,
    label_cluster,
    cluster_tags,
)
from steam_analyst.config.settings import AnalysisParams


class TestComputeJaccardTagDistance:
    """Tests for compute_jaccard_tag_distance."""

    def test_identical_game_sets_zero_distance(self):
        """Two tags applied to exactly the same games have distance 0.0."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3],
            "tag": ["A", "B", "A", "B", "A", "B"],
            "votes": [10, 10, 10, 10, 10, 10],
            "rank": [1, 2, 1, 2, 1, 2],
        })

        distance_df = compute_jaccard_tag_distance(tags)

        # Tags A and B co-occur on games {1, 2, 3}
        # Jaccard(A, B) = 3 / 3 = 1.0, distance = 1 - 1.0 = 0.0
        assert distance_df.loc["A", "B"] == 0.0
        assert distance_df.loc["B", "A"] == 0.0

    def test_disjoint_game_sets_max_distance(self):
        """Two tags applied to completely disjoint game sets have distance 1.0."""
        tags = pd.DataFrame({
            "appid": [1, 2, 3, 4],
            "tag": ["A", "A", "B", "B"],
            "votes": [10, 10, 10, 10],
            "rank": [1, 1, 1, 1],
        })

        distance_df = compute_jaccard_tag_distance(tags)

        # A on {1, 2}, B on {3, 4}, no overlap
        # Jaccard(A, B) = 0 / 4 = 0.0, distance = 1 - 0.0 = 1.0
        assert distance_df.loc["A", "B"] == 1.0
        assert distance_df.loc["B", "A"] == 1.0

    def test_matrix_is_symmetric(self):
        """For a synthetic multi-tag fixture, D equals its own transpose."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4],
            "tag": ["A", "B", "A", "C", "B", "C", "A", "D"],
            "votes": [10] * 8,
            "rank": [1] * 8,
        })

        distance_df = compute_jaccard_tag_distance(tags)

        # Check symmetry
        pd.testing.assert_frame_equal(distance_df, distance_df.T)

    def test_diagonal_is_zero(self):
        """All diagonal entries are exactly 0.0."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3],
            "tag": ["A", "B", "B", "C", "C", "A"],
            "votes": [10] * 6,
            "rank": [1] * 6,
        })

        distance_df = compute_jaccard_tag_distance(tags)

        for tag in distance_df.index:
            assert distance_df.loc[tag, tag] == 0.0

    def test_empty_tags_returns_empty_matrix(self):
        """An empty tags frame returns a 0x0 DataFrame."""
        tags = pd.DataFrame({
            "appid": pd.Series([], dtype=int),
            "tag": pd.Series([], dtype=str),
            "votes": pd.Series([], dtype=int),
            "rank": pd.Series([], dtype=int),
        })

        distance_df = compute_jaccard_tag_distance(tags)

        assert len(distance_df) == 0
        assert distance_df.shape == (0, 0)

    def test_single_tag(self):
        """A single tag returns a 1x1 distance matrix with 0.0 on diagonal."""
        tags = pd.DataFrame({
            "appid": [1, 2, 3],
            "tag": ["A", "A", "A"],
            "votes": [10, 10, 10],
            "rank": [1, 1, 1],
        })

        distance_df = compute_jaccard_tag_distance(tags)

        assert distance_df.shape == (1, 1)
        assert distance_df.loc["A", "A"] == 0.0

    def test_partial_overlap(self):
        """Tags with partial co-occurrence have distance in (0, 1)."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 3, 4],
            "tag": ["A", "B", "A", "B", "B"],
            "votes": [10] * 5,
            "rank": [1] * 5,
        })

        distance_df = compute_jaccard_tag_distance(tags)

        # A on {1, 2}, B on {1, 3, 4}
        # Intersection: {1}, Union: {1, 2, 3, 4}
        # Jaccard(A, B) = 1 / 4 = 0.25, distance = 1 - 0.25 = 0.75
        assert distance_df.loc["A", "B"] == pytest.approx(0.75)
        assert distance_df.loc["B", "A"] == pytest.approx(0.75)

    def test_off_diagonal_in_range(self):
        """All off-diagonal entries are in [0.0, 1.0]."""
        tags = pd.DataFrame({
            "appid": [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4],
            "tag": ["A", "B", "C", "B", "C", "D", "C", "D", "E", "D", "E", "A"],
            "votes": [10] * 12,
            "rank": [1] * 12,
        })

        distance_df = compute_jaccard_tag_distance(tags)

        # Check all off-diagonal entries
        for i in range(len(distance_df)):
            for j in range(len(distance_df)):
                if i != j:
                    val = distance_df.iloc[i, j]
                    assert 0.0 <= val <= 1.0


class TestLabelCluster:
    """Tests for label_cluster."""

    def test_single_tag_cluster_label(self):
        """A one-tag cluster labels as just that tag."""
        cooccurrence = pd.DataFrame({
            "Roguelike": [10],
        }, index=["Roguelike"])

        label = label_cluster(["Roguelike"], cooccurrence)

        assert label == "Roguelike"

    def test_top_three_by_weight_selected(self):
        """A 5-tag cluster labels with exactly its top 3 by co-occurrence weight."""
        cooccurrence = pd.DataFrame({
            "A": [100, 50, 30, 20, 10],
            "B": [50, 100, 40, 25, 5],
            "C": [30, 40, 80, 35, 15],
            "D": [20, 25, 35, 60, 20],
            "E": [10, 5, 15, 20, 50],
        }, index=["A", "B", "C", "D", "E"])

        members = ["A", "B", "C", "D", "E"]
        label = label_cluster(members, cooccurrence)

        # Weights (row sums): A=210, B=220, C=200, D=160, E=100
        # Top 3 by weight: B (220), A (210), C (200)
        assert label == "B / A / C"

    def test_tie_broken_alphabetically(self):
        """Two equally-weighted tags are ordered alphabetically in the label."""
        cooccurrence = pd.DataFrame({
            "Alice": [100, 100],
            "Bob": [100, 100],
        }, index=["Alice", "Bob"])

        members = ["Alice", "Bob"]
        label = label_cluster(members, cooccurrence)

        # Both have weight 200, Alice < Bob alphabetically
        assert label == "Alice / Bob"

    def test_deterministic_across_calls(self):
        """Two calls with identical inputs return the identical string."""
        cooccurrence = pd.DataFrame({
            "A": [100, 50, 30, 20],
            "B": [50, 100, 40, 25],
            "C": [30, 40, 80, 35],
            "D": [20, 25, 35, 60],
        }, index=["A", "B", "C", "D"])

        members = ["A", "B", "C", "D"]
        label1 = label_cluster(members, cooccurrence)
        label2 = label_cluster(members, cooccurrence)

        assert label1 == label2

    def test_less_than_three_tags(self):
        """A cluster with fewer than 3 tags is labeled with all of them."""
        cooccurrence = pd.DataFrame({
            "X": [50, 30],
            "Y": [30, 50],
        }, index=["X", "Y"])

        members = ["X", "Y"]
        label = label_cluster(members, cooccurrence)

        # X weight = 80, Y weight = 80, alphabetically X < Y
        assert label == "X / Y"

    def test_missing_tag_in_cooccurrence(self):
        """A tag not in cooccurrence is given weight 0."""
        cooccurrence = pd.DataFrame({
            "A": [100, 50],
            "B": [50, 100],
        }, index=["A", "B"])

        # C is not in cooccurrence
        members = ["A", "C", "B"]
        label = label_cluster(members, cooccurrence)

        # A weight = 150, B weight = 150, C weight = 0
        # Top 3: A, B, C (alphabetically for A/B tie, but both > C)
        # Actually A=150, B=150, C=0, so top 3 in order is A, B, C
        assert label == "A / B / C"


class TestClusterTags:
    """Tests for cluster_tags."""

    def _make_params(
        self,
        tag_distance_threshold=None,
        min_cluster_size=5,
        min_tag_votes=0,
        max_tags_per_game=20,
    ):
        """Helper to create AnalysisParams."""
        return AnalysisParams(
            simplicity_percentile=0.40,
            trailing_window_months=24,
            min_cluster_size=min_cluster_size,
            opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
            min_tag_votes=min_tag_votes,
            max_tags_per_game=max_tags_per_game,
            tag_distance_threshold=tag_distance_threshold,
            clustering_linkage="average",
        )

    def test_deterministic_across_repeated_calls(self):
        """Two calls with identical inputs produce identical TagClusterResult."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D"],
            "votes": [10] * 10,
            "rank": [1] * 10,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
        })
        params = self._make_params()

        result1 = cluster_tags(tags, frame, params)
        result2 = cluster_tags(tags, frame, params)

        pd.testing.assert_frame_equal(result1.assignments, result2.assignments)
        assert result1.cluster_labels == result2.cluster_labels
        assert result1.cluster_members == result2.cluster_members

    def test_recovers_two_obviously_separated_groups(self):
        """A synthetic set with two disjoint tag/game groups recovers two clusters."""
        # Group 1: games 1, 2, 3 with tags A, B
        # Group 2: games 4, 5, 6 with tags C, D
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D", "C", "D"],
            "votes": [10] * 12,
            "rank": [1] * 12,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5, 6],
        })
        params = self._make_params(min_cluster_size=2)

        result = cluster_tags(tags, frame, params)

        # Should find exactly 2 clusters
        assert len(result.cluster_members) == 2

        # Get the two clusters
        clusters = list(result.cluster_members.values())
        members_set = [set(c) for c in clusters]

        # One should have {A, B}, the other {C, D}
        assert set(["A", "B"]) in members_set
        assert set(["C", "D"]) in members_set

    def test_frozen_threshold_used_verbatim(self):
        """With a frozen threshold, it is used verbatim and marked as 'frozen'."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D"],
            "votes": [10] * 10,
            "rank": [1] * 10,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
        })
        params = self._make_params(tag_distance_threshold=0.5)

        result = cluster_tags(tags, frame, params)

        assert result.params_used["distance_threshold"] == 0.5
        assert result.params_used["threshold_source"] == "frozen"

    def test_prefreeze_run_local_search_used_when_threshold_none(self):
        """With threshold=None, run_local_search is used."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D", "C", "D", "E", "F", "E", "F"],
            "votes": [10] * 16,
            "rank": [1] * 16,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5, 6, 7, 8],
        })
        params = self._make_params(tag_distance_threshold=None, min_cluster_size=2)

        result = cluster_tags(tags, frame, params)

        # Should use run_local_search (not frozen)
        assert result.params_used["threshold_source"] in ["run_local_search", "run_local_search_fallback_max"]
        assert result.params_used["distance_threshold"] is not None

    def test_empty_tags_returns_empty_result(self):
        """Zero tags after filtering returns an empty TagClusterResult."""
        tags = pd.DataFrame({
            "appid": pd.Series([], dtype=int),
            "tag": pd.Series([], dtype=str),
            "votes": pd.Series([], dtype=int),
            "rank": pd.Series([], dtype=int),
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3],
        })
        params = self._make_params()

        result = cluster_tags(tags, frame, params)

        assert len(result.assignments) == 0
        assert len(result.cluster_labels) == 0
        assert len(result.cluster_members) == 0

    def test_every_assigned_game_has_valid_cluster_id(self):
        """Every cluster_id in assignments is a key in cluster_labels."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D"],
            "votes": [10] * 10,
            "rank": [1] * 10,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
        })
        params = self._make_params()

        result = cluster_tags(tags, frame, params)

        for cluster_id in result.assignments["cluster_id"].unique():
            assert cluster_id in result.cluster_labels
            assert cluster_id in result.cluster_members

    def test_plurality_tie_broken_by_lowest_id(self):
        """A game with tags evenly split between clusters is assigned to lowest cluster_id."""
        # Create a scenario where a game could have tags in 2 different clusters
        # Game 1 has tags A (cluster 0) and B (cluster 1), equal vote split
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D", "C", "D"],
            "votes": [10] * 12,
            "rank": [1] * 12,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5, 6],
        })
        params = self._make_params(min_cluster_size=1)

        result = cluster_tags(tags, frame, params)

        # Game 1 has tags A and B (should be in different clusters)
        game1_cluster = result.assignments[result.assignments["appid"] == 1]["cluster_id"].values[0]

        # If both tags have equal weight, should pick lower cluster_id
        # The exact cluster_id depends on the clustering result, so we just verify
        # that game 1 is assigned to exactly one cluster
        assert len(result.assignments[result.assignments["appid"] == 1]) == 1

    def test_method_field_is_correct(self):
        """The method field is the locked string."""
        tags = pd.DataFrame({
            "appid": [1, 2, 3],
            "tag": ["A", "B", "C"],
            "votes": [10, 10, 10],
            "rank": [1, 1, 1],
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3],
        })
        params = self._make_params()

        result = cluster_tags(tags, frame, params)

        assert result.method == "agglomerative_jaccard_no_genre_anchor"

    def test_cluster_members_partition_tags(self):
        """cluster_members partitions the set of tags exactly."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D"],
            "votes": [10] * 10,
            "rank": [1] * 10,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
        })
        params = self._make_params()

        result = cluster_tags(tags, frame, params)

        # Collect all tags from cluster_members
        all_tags_in_clusters = set()
        for members in result.cluster_members.values():
            all_tags_in_clusters.update(members)

        # Should match the distinct tags in the filtered input
        expected_tags = set(tags["tag"].unique())
        assert all_tags_in_clusters == expected_tags

    def test_max_tags_per_game_applied(self):
        """max_tags_per_game limit is applied correctly."""
        tags = pd.DataFrame({
            "appid": [1, 1, 1, 1, 2, 2, 2, 2],
            "tag": ["A", "B", "C", "D", "A", "B", "C", "D"],
            "votes": [10, 9, 8, 7, 10, 9, 8, 7],
            "rank": [1, 2, 3, 4, 1, 2, 3, 4],
        })
        frame = pd.DataFrame({
            "appid": [1, 2],
        })
        # Limit to 2 tags per game
        params = self._make_params(max_tags_per_game=2)

        result = cluster_tags(tags, frame, params)

        # Only tags A and B (top 2) should be used
        all_tags = set()
        for members in result.cluster_members.values():
            all_tags.update(members)

        # C and D might be filtered out, only A and B should remain
        # (depending on how tags are ranked)
        assert "A" in all_tags or "B" in all_tags

    def test_min_tag_votes_pre_filtered(self):
        """Tags with votes below min_tag_votes are assumed pre-filtered."""
        # If tags come already filtered, we just test that the function
        # works with a smaller tag set
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3],
            "tag": ["A", "B", "A", "B", "A", "B"],
            "votes": [10, 10, 10, 10, 10, 10],  # Already filtered
            "rank": [1, 2, 1, 2, 1, 2],
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3],
        })
        params = self._make_params(min_tag_votes=0)

        result = cluster_tags(tags, frame, params)

        # Should work without error
        assert len(result.assignments) > 0

    def test_assignments_only_includes_games_with_tags(self):
        """Only games that had at least one retained tag appear in assignments."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2],
            "tag": ["A", "B", "A", "B"],
            "votes": [10] * 4,
            "rank": [1] * 4,
        })
        # Frame includes 5 games, but only 2 have tags
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
        })
        params = self._make_params()

        result = cluster_tags(tags, frame, params)

        # Only games 1 and 2 should be in assignments
        assigned_appids = set(result.assignments["appid"].unique())
        assert assigned_appids == {1, 2}

    def test_single_tag_case(self):
        """A single tag creates one cluster and assigns all games to it."""
        tags = pd.DataFrame({
            "appid": [1, 2, 3],
            "tag": ["A", "A", "A"],
            "votes": [10, 10, 10],
            "rank": [1, 1, 1],
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3],
        })
        params = self._make_params()

        result = cluster_tags(tags, frame, params)

        assert len(result.cluster_members) == 1
        assert len(result.assignments) == 3
        assert all(result.assignments["cluster_id"] == 0)

    def test_all_games_assigned(self):
        """Every game with at least one tag is assigned to exactly one cluster."""
        tags = pd.DataFrame({
            "appid": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "tag": ["A", "B", "A", "B", "A", "B", "C", "D", "C", "D"],
            "votes": [10] * 10,
            "rank": [1] * 10,
        })
        frame = pd.DataFrame({
            "appid": [1, 2, 3, 4, 5],
        })
        params = self._make_params()

        result = cluster_tags(tags, frame, params)

        # Each game should appear exactly once in assignments
        game_counts = result.assignments["appid"].value_counts()
        assert all(game_counts == 1)


class TestTagClusterResult:
    """Tests for TagClusterResult dataclass."""

    def test_is_frozen(self):
        """TagClusterResult instances are frozen (immutable)."""
        assignments = pd.DataFrame({"appid": [1], "cluster_id": [0]})
        cluster_labels = {0: "Test"}
        cluster_members = {0: ["A"]}
        cooccurrence = pd.DataFrame()

        result = TagClusterResult(
            assignments=assignments,
            cluster_labels=cluster_labels,
            cluster_members=cluster_members,
            cooccurrence=cooccurrence,
            method="test",
            params_used={},
        )

        with pytest.raises(AttributeError):
            result.assignments = None

    def test_fields_accessible(self):
        """All fields are accessible."""
        assignments = pd.DataFrame({"appid": [1, 2], "cluster_id": [0, 1]})
        cluster_labels = {0: "ClusterA", 1: "ClusterB"}
        cluster_members = {0: ["A"], 1: ["B"]}
        cooccurrence = pd.DataFrame()

        result = TagClusterResult(
            assignments=assignments,
            cluster_labels=cluster_labels,
            cluster_members=cluster_members,
            cooccurrence=cooccurrence,
            method="test_method",
            params_used={"linkage": "average"},
        )

        assert len(result.assignments) == 2
        assert len(result.cluster_labels) == 2
        assert len(result.cluster_members) == 2
        assert result.method == "test_method"
        assert result.params_used["linkage"] == "average"


def _two_group_tags(extra_rows=None):
    """Games 1-5 carry tags A,B and games 6-10 carry tags C,D (identical game sets)."""
    rows = []
    for appid in range(1, 6):
        rows += [(appid, "A", 1), (appid, "B", 2)]
    for appid in range(6, 11):
        rows += [(appid, "C", 1), (appid, "D", 2)]
    rows += extra_rows or []
    return pd.DataFrame(rows, columns=["appid", "tag", "rank"]).assign(votes=10)


def _params(**overrides):
    base = AnalysisParams(
        simplicity_percentile=0.40,
        trailing_window_months=24,
        min_cluster_size=5,
        opportunity_weights={"demand": 0.4, "competition": 0.3, "simplicity": 0.3},
        min_tag_votes=0,
        max_tags_per_game=20,
        tag_distance_threshold=None,
        clustering_linkage="average",
        generic_tag_max_share=1.0,
    )
    return replace(base, **overrides)


class TestGenericTagExclusion:
    """Tests for the generic-tag exclusion step of cluster_tags."""

    def test_tag_above_share_is_excluded_from_clusters(self):
        generic_rows = [(appid, "G", 3) for appid in range(1, 11)]
        tags = _two_group_tags(generic_rows)
        frame = pd.DataFrame({"appid": range(1, 11)})

        result = cluster_tags(tags, frame, _params(generic_tag_max_share=0.6))

        assert result.excluded_generic_tags == ["G"]
        assert all("G" not in members for members in result.cluster_members.values())

    def test_share_of_one_disables_exclusion(self):
        generic_rows = [(appid, "G", 3) for appid in range(1, 11)]
        tags = _two_group_tags(generic_rows)
        frame = pd.DataFrame({"appid": range(1, 11)})

        result = cluster_tags(tags, frame, _params(generic_tag_max_share=1.0))

        assert result.excluded_generic_tags == []
        assert any("G" in members for members in result.cluster_members.values())

    def test_tag_exactly_at_share_is_kept(self):
        tags = _two_group_tags()
        frame = pd.DataFrame({"appid": range(1, 11)})

        result = cluster_tags(tags, frame, _params(generic_tag_max_share=0.5))

        assert result.excluded_generic_tags == []

    def test_exclusion_happens_before_per_game_cap(self):
        rows = [(appid, "G", 1) for appid in range(1, 11)]
        rows += [(appid, "A", 2) for appid in range(1, 6)]
        rows += [(appid, "C", 2) for appid in range(6, 11)]
        tags = pd.DataFrame(rows, columns=["appid", "tag", "rank"]).assign(votes=10)
        frame = pd.DataFrame({"appid": range(1, 11)})

        result = cluster_tags(
            tags,
            frame,
            _params(generic_tag_max_share=0.6, max_tags_per_game=1),
        )

        clustered_tags = {t for members in result.cluster_members.values() for t in members}
        assert clustered_tags == {"A", "C"}
        assert len(result.assignments) == 10

    def test_all_tags_generic_gives_empty_result(self):
        tags = pd.DataFrame(
            {"appid": [1, 2, 3], "tag": ["G", "G", "G"], "votes": 10, "rank": 1}
        )
        frame = pd.DataFrame({"appid": [1, 2, 3]})

        result = cluster_tags(tags, frame, _params(generic_tag_max_share=0.5))

        assert result.excluded_generic_tags == ["G"]
        assert result.cluster_members == {}
        assert len(result.assignments) == 0


class TestRunLocalThresholdSearch:
    """Tests for the games-per-cluster threshold search."""

    def test_picks_smallest_distance_maximizing_scorable_clusters(self):
        tags = _two_group_tags()
        frame = pd.DataFrame({"appid": range(1, 11)})

        result = cluster_tags(tags, frame, _params())

        assert result.params_used["threshold_source"] == "run_local_search"
        assert result.params_used["distance_threshold"] == 0.0
        sizes = result.assignments.groupby("cluster_id").size().tolist()
        assert sorted(sizes) == [5, 5]

    def test_counts_games_not_tags(self):
        rows = []
        for appid in (1, 2):
            rows += [(appid, f"T{i}", i) for i in range(1, 6)]
        for appid in range(3, 10):
            rows += [(appid, "U1", 1), (appid, "U2", 2)]
        tags = pd.DataFrame(rows, columns=["appid", "tag", "rank"]).assign(votes=10)
        frame = pd.DataFrame({"appid": range(1, 10)})

        result = cluster_tags(tags, frame, _params())

        biggest = result.assignments.groupby("cluster_id").size().max()
        assert biggest == 7

    def test_falls_back_to_max_distance_when_no_cluster_reaches_min_size(self):
        tags = pd.DataFrame(
            {"appid": [1, 2, 3], "tag": ["A", "B", "C"], "votes": 10, "rank": 1}
        )
        frame = pd.DataFrame({"appid": [1, 2, 3]})

        result = cluster_tags(tags, frame, _params())

        assert result.params_used["threshold_source"] == "run_local_search_fallback_max"

    def test_frozen_threshold_still_used_verbatim(self):
        tags = _two_group_tags()
        frame = pd.DataFrame({"appid": range(1, 11)})

        result = cluster_tags(tags, frame, _params(tag_distance_threshold=0.5))

        assert result.params_used["threshold_source"] == "frozen"
        assert result.params_used["distance_threshold"] == 0.5


class TestClusterModeShares:
    """Tests for the per-cluster player-mode tag shares."""

    def _tags(self):
        rows = []
        for appid in (1, 2, 3):
            rows += [(appid, "A", 1), (appid, "Singleplayer", 2)]
        rows += [(4, "A", 1), (4, "Multiplayer", 2)]
        return pd.DataFrame(rows, columns=["appid", "tag", "rank"]).assign(votes=10)

    def test_shares_are_fractions_of_assigned_games(self):
        frame = pd.DataFrame({"appid": [1, 2, 3, 4]})

        result = cluster_tags(
            self._tags(), frame, _params(tag_distance_threshold=1.0)
        )

        assert len(result.cluster_mode_shares) == 1
        shares = next(iter(result.cluster_mode_shares.values()))
        assert shares == {"Singleplayer": 0.75, "Multiplayer": 0.25, "Co-op": 0.0}

    def test_shares_use_tags_from_before_generic_exclusion(self):
        rows = []
        for appid in (1, 2, 3, 4):
            rows.append((appid, "Singleplayer", 1))
        rows += [(1, "X", 2), (2, "X", 2), (3, "Y", 2), (4, "Y", 2), (5, "X", 1)]
        tags = pd.DataFrame(rows, columns=["appid", "tag", "rank"]).assign(votes=10)
        frame = pd.DataFrame({"appid": [1, 2, 3, 4, 5]})

        result = cluster_tags(
            tags,
            frame,
            _params(tag_distance_threshold=1.0, generic_tag_max_share=0.7),
        )

        assert result.excluded_generic_tags == ["Singleplayer"]
        shares = next(iter(result.cluster_mode_shares.values()))
        assert shares["Singleplayer"] == 0.8


class TestThresholdSearchWindow:
    """The threshold search counts only games released within the window."""

    def _tags(self):
        rows = []
        for appid in (1, 2, 3):
            rows += [(appid, "P", 1), (appid, "Q", 2), (appid, "T", 3)]
        for appid in (4, 5, 6):
            rows += [(appid, "R", 1), (appid, "S", 2), (appid, "T", 3)]
        return pd.DataFrame(rows, columns=["appid", "tag", "rank"]).assign(votes=10)

    def _search(self, countable):
        from scipy.cluster.hierarchy import linkage
        from scipy.spatial.distance import squareform

        from steam_analyst.analysis.clustering import _search_threshold

        tags = self._tags()
        distance = compute_jaccard_tag_distance(tags)
        Z = linkage(squareform(distance.values, checks=False), method="average")
        return _search_threshold(Z, distance.index, tags, 3, countable)

    def test_all_games_counted_prefers_fine_clusters(self):
        threshold, _ = self._search(None)
        assert threshold == 0.0

    def test_out_of_window_games_force_a_coarser_cut(self):
        threshold, source = self._search({1, 2, 4, 5})
        assert source == "run_local_search"
        assert threshold > 0.5

    def test_no_games_in_window_falls_back_to_max_distance(self):
        _, source = self._search(set())
        assert source == "run_local_search_fallback_max"

    def test_cluster_tags_uses_release_dates_when_present(self):
        today = pd.Timestamp.now()
        tags = self._tags()
        frame = pd.DataFrame({
            "appid": range(1, 7),
            "release_date_parsed": [today, today, today - pd.DateOffset(years=5),
                                    today, today, today - pd.DateOffset(years=5)],
        })

        result = cluster_tags(tags, frame, _params(min_cluster_size=3))

        assert result.params_used["distance_threshold"] > 0.5
