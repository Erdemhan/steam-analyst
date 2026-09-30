"""Tests for the Info page."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from steam_analyst.ui import info_page

PARAMETERS_PATH = Path(__file__).resolve().parents[3] / "config" / "parameters.toml"

_SCRIPT_TEMPLATE = """
from pathlib import Path
from unittest.mock import Mock

from steam_analyst.ui.info_page import render_info_page

settings = Mock()
settings.parameters_path = Path({path!r})
render_info_page(Mock(), settings)
"""


def _run(path: Path) -> AppTest:
    at = AppTest.from_string(_SCRIPT_TEMPLATE.format(path=str(path)))
    at.run(timeout=60)
    return at


def test_flatten_and_format_helpers() -> None:
    rows = info_page._flatten({"a": {"b": 1, "c": [1, 2]}, "d": True})
    assert ("a.b", 1) in rows
    assert ("a.c", [1, 2]) in rows
    assert ("d", True) in rows
    assert info_page._format_value(True) == "evet"
    assert info_page._format_value([1, 2]) == "1, 2"


def test_info_page_renders_with_real_parameters() -> None:
    at = _run(PARAMETERS_PATH)
    assert not at.exception
    assert [h.value for h in at.header] == ["Bilgi"]
    subheaders = [h.value for h in at.subheader]
    assert "Akış diyagramı" in subheaders
    assert "Mevcut parametreler" in subheaders
    assert "Eksik ve güncellenmesi gereken noktalar" in subheaders
    assert len(at.dataframe) == 3


def test_info_page_survives_missing_parameters_file(tmp_path: Path) -> None:
    at = _run(tmp_path / "does-not-exist.toml")
    assert not at.exception
    assert any("okunamadı" in w.value for w in at.warning)
