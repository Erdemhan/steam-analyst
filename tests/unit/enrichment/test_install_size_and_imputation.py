"""Tests for install-size parsing, early-access detection and imputation flags."""

import pandas as pd
import pytest

from steam_analyst.enrichment.complexity import (
    compute_complexity_details,
    compute_complexity_score,
)
from steam_analyst.enrichment.parsing import parse_install_size_bytes, parse_is_early_access


def _req(storage_line: str) -> dict:
    return {
        "minimum": (
            '<strong>Minimum:</strong><br><ul class="bb_ul"><li><strong>OS:</strong> Windows 10<br></li>'
            f"<li><strong>Memory:</strong> 8 GB RAM<br></li>{storage_line}</ul>"
        )
    }


class TestParseInstallSizeBytes:
    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            ("<li><strong>Storage:</strong> 9 GB available space</li>", 9_000_000_000),
            ("<li><strong>Hard Drive:</strong> 500 MB</li>", 500_000_000),
            ("<li><strong>Hard Disk Space:</strong> 1.5 GB</li>", 1_500_000_000),
            ("<li><strong>Storage:</strong> 1,5 GB available space<br></li>", 1_500_000_000),
            ("<li><strong>Storage:</strong> 2 TB</li>", 2_000_000_000_000),
            ("<li><strong>Disk Space:</strong> 512 MiB</li>", 512 * 1024**2),
        ],
    )
    def test_parses_common_storage_lines(self, line: str, expected: int) -> None:
        assert parse_install_size_bytes(_req(line)) == expected

    def test_memory_line_is_not_mistaken_for_storage(self) -> None:
        assert parse_install_size_bytes(_req("")) is None

    def test_falls_back_to_recommended_block(self) -> None:
        req = {
            "minimum": "<ul><li><strong>OS:</strong> Windows 10</li></ul>",
            "recommended": "<ul><li><strong>Storage:</strong> 20 GB available space</li></ul>",
        }
        assert parse_install_size_bytes(req) == 20_000_000_000

    @pytest.mark.parametrize("value", [[], None, "text", {}, {"minimum": ""}, {"minimum": None}])
    def test_absent_or_malformed_requirements_give_none(self, value) -> None:
        assert parse_install_size_bytes(value) is None

    def test_zero_size_is_rejected(self) -> None:
        assert parse_install_size_bytes(_req("<li><strong>Storage:</strong> 0 MB</li>")) is None


class TestParseIsEarlyAccess:
    def test_detects_genre_id_70(self) -> None:
        assert parse_is_early_access([{"id": "1", "description": "Action"}, {"id": "70", "description": "Early Access"}])

    def test_detects_description_without_id(self) -> None:
        assert parse_is_early_access([{"description": "early access"}])

    def test_absent_genres_are_not_early_access(self) -> None:
        assert parse_is_early_access(None) is False
        assert parse_is_early_access([]) is False
        assert parse_is_early_access([{"id": "1", "description": "Action"}]) is False


def _params():
    from steam_analyst.config.settings import EnrichmentParams

    return EnrichmentParams(
        boxleiter_multipliers={},
        genre_bucket_map={},
        storefront_cut=0.30,
        discount_factor=0.0,
        refund_regional_factor=0.0,
        complexity_weights={
            "size_bytes": 0.20,
            "ram_bytes": 0.10,
            "early_access_days": 0.05,
            "dev_title_count": 0.15,
            "simplicity_tag_score": 0.10,
            "complexity_tag_score": 0.10,
            "achievement_count": 0.10,
            "dlc_count": 0.10,
            "platform_count": 0.05,
            "language_count": 0.05,
        },
        complexity_bounds={"size_bytes": (6.0, 10.0), "achievement_count": (0.0, 2.0)},
        simplicity_tags=["2D"],
        complexity_tags=["Open World"],
        effort_epsilon=0.05,
        tag_extraction_max_per_game=20,
        tag_extraction_min_votes=0,
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "size_bytes": [1e9, float("nan"), 5e9],
            "ram_bytes": [1e9, float("nan"), 5e9],
            "early_access_days": [float("nan")] * 3,
            "is_early_access": [False, False, False],
            "dev_title_count": [3, 4, 5],
            "achievement_count": [10, 20, float("nan")],
            "dlc_count": [0, 1, 2],
            "platform_count": [1, 2, 3],
            "language_count": [2, 3, 4],
        },
        index=pd.Index([1, 2, 3], name="appid"),
    )


def _tags() -> pd.DataFrame:
    return pd.DataFrame(
        {"appid": [1, 2, 3], "tag": ["2D", "2D", "Open World"], "votes": [1, 1, 1], "rank": [1, 1, 1]}
    )


class TestImputationFlags:
    def test_flags_mark_exactly_the_raw_missing_entries(self) -> None:
        _, _, imputed = compute_complexity_details(_frame(), _tags(), _params())
        assert imputed.dtypes.eq(bool).all()
        assert bool(imputed.loc[2, "size_bytes"]) is True
        assert bool(imputed.loc[1, "size_bytes"]) is False
        assert bool(imputed.loc[3, "achievement_count"]) is True
        assert not imputed.loc[1].any()

    def test_wrapper_matches_details_score_and_contributions(self) -> None:
        score, contributions = compute_complexity_score(_frame(), _tags(), _params())
        score_d, contributions_d, _ = compute_complexity_details(_frame(), _tags(), _params())
        pd.testing.assert_series_equal(score, score_d)
        pd.testing.assert_frame_equal(contributions, contributions_d)

    def test_empty_frame_returns_three_empty_objects(self) -> None:
        score, contributions, imputed = compute_complexity_details(pd.DataFrame(), pd.DataFrame(), _params())
        assert len(score) == 0 and contributions.empty and imputed.empty
