"""Tests for dropping software apps (by Steam genre) during enrichment."""

from steam_analyst.enrichment.parsing import (
    RawBundle,
    normalize_features,
    software_excluded_appids,
)

SOFTWARE = ("Utilities", "Game Development")


def _app(appid, genres, app_type="game"):
    return {
        "success": True,
        "data": {
            "name": f"App {appid}",
            "type": app_type,
            "genres": [{"id": str(i), "description": g} for i, g in enumerate(genres)],
        },
    }


def _bundle(apps):
    return RawBundle(
        run_id="r",
        steamspy={a: {"name": f"App {a}", "positive": 10, "negative": 1} for a in apps},
        steamspy_appdetails={a: {"tags": {}} for a in apps},
        appdetails=apps,
        reviews={},
    )


class TestSoftwareExcludedAppids:
    def test_flags_apps_with_a_software_genre(self):
        bundle = _bundle({1: _app(1, ["Action", "Utilities"]), 2: _app(2, ["Action", "Indie"])})
        assert software_excluded_appids(bundle, SOFTWARE) == {1}

    def test_empty_genre_list_flags_nothing(self):
        bundle = _bundle({1: _app(1, ["Utilities"])})
        assert software_excluded_appids(bundle, ()) == set()

    def test_education_alone_is_not_software(self):
        bundle = _bundle({1: _app(1, ["Education", "Indie"])})
        assert software_excluded_appids(bundle, SOFTWARE) == set()

    def test_missing_or_malformed_genres_are_ignored(self):
        apps = {
            1: {"success": True, "data": {"type": "game"}},
            2: {"success": True, "data": {"type": "game", "genres": "Utilities"}},
            3: {"success": False},
            4: {},
        }
        assert software_excluded_appids(_bundle(apps), SOFTWARE) == set()


class TestNormalizeFeaturesIsGame:
    def test_software_genre_makes_the_app_not_a_game(self):
        bundle = _bundle({1: _app(1, ["Indie", "Game Development"]), 2: _app(2, ["Indie"])})
        frame = normalize_features(bundle, SOFTWARE)
        assert bool(frame.loc[1, "is_game"]) is False
        assert bool(frame.loc[2, "is_game"]) is True

    def test_default_keeps_software_apps_as_games(self):
        bundle = _bundle({1: _app(1, ["Utilities"])})
        assert bool(normalize_features(bundle).loc[1, "is_game"]) is True
