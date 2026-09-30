"""Tests for parse_ram_bytes and the ram_bytes feature wiring."""

import pytest

from steam_analyst.enrichment.parsing import parse_ram_bytes


def _req(minimum: str = "", recommended: str = "") -> dict:
    return {"minimum": minimum, "recommended": recommended}


class TestParseRamBytes:
    def test_memory_line_in_gb(self):
        html = "<ul><li><strong>Memory:</strong> 8 GB RAM<br></li></ul>"
        assert parse_ram_bytes(_req(html)) == 8_000_000_000

    def test_memory_line_in_mb(self):
        html = "<ul><li><strong>Memory:</strong> 512 MB RAM</li></ul>"
        assert parse_ram_bytes(_req(html)) == 512_000_000

    def test_ram_label_variant(self):
        html = "<ul><li><strong>RAM:</strong> 4 GB</li></ul>"
        assert parse_ram_bytes(_req(html)) == 4_000_000_000

    def test_video_memory_line_is_ignored(self):
        html = (
            "<ul><li><strong>Video Memory:</strong> 2 GB</li>"
            "<li><strong>Graphics:</strong> 2 GB Memory</li></ul>"
        )
        assert parse_ram_bytes(_req(html)) is None

    def test_video_memory_does_not_shadow_system_memory(self):
        html = (
            "<ul><li><strong>Video Memory:</strong> 2 GB</li>"
            "<li><strong>Memory:</strong> 16 GB RAM</li></ul>"
        )
        assert parse_ram_bytes(_req(html)) == 16_000_000_000

    def test_storage_line_not_mistaken_for_ram(self):
        html = "<ul><li><strong>Storage:</strong> 50 GB available space</li></ul>"
        assert parse_ram_bytes(_req(html)) is None

    def test_falls_back_to_recommended(self):
        rec = "<ul><li><strong>Memory:</strong> 12 GB RAM</li></ul>"
        assert parse_ram_bytes(_req("", rec)) == 12_000_000_000

    def test_prefers_minimum_over_recommended(self):
        minimum = "<ul><li><strong>Memory:</strong> 4 GB RAM</li></ul>"
        rec = "<ul><li><strong>Memory:</strong> 16 GB RAM</li></ul>"
        assert parse_ram_bytes(_req(minimum, rec)) == 4_000_000_000

    def test_decimal_comma(self):
        html = "<li><strong>Memory:</strong> 1,5 GB RAM</li>"
        assert parse_ram_bytes(_req(html)) == 1_500_000_000

    @pytest.mark.parametrize("value", [[], None, "text", {}, {"minimum": ""}, {"minimum": 5}])
    def test_absent_or_malformed_returns_none(self, value):
        assert parse_ram_bytes(value) is None

    def test_zero_size_returns_none(self):
        html = "<li><strong>Memory:</strong> 0 MB RAM</li>"
        assert parse_ram_bytes(_req(html)) is None
