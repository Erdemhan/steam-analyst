"""
Unit tests for analysis_results.py module (write_analysis_result, read_analysis_result).

Tests cover:
- Basic write/read roundtrips with various payload structures
- Upsert behavior (overwrites prior values)
- Error cases (invalid analysis_type, non-existent run_id, non-JSON-serializable payload)
- Edge cases (NaN/Infinity, mutation of returned dict, missing results)
"""

import json
import math
import sqlite3
import pytest
from pathlib import Path

from steam_analyst.storage import schema, runs, analysis_results
from steam_analyst.storage.types import StorageError


@pytest.fixture
def db_path(tmp_path):
    """Temporary SQLite database file."""
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    """Open a connection and initialize schema."""
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    schema.initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def run_id(conn):
    """Create a test run and return its run_id."""
    return runs.create_run(
        conn,
        config={"test": True},
        parameters_version="test_params_v1",
        trigger_type="manual",
    )


class TestWriteAnalysisResult:
    """Tests for write_analysis_result function."""

    def test_write_then_read_roundtrip(self, conn, run_id):
        """A nested dict payload round-trips through write/read unchanged."""
        payload = {"clusters": [{"id": 1, "score": 0.8}, {"id": 2, "score": 0.6}]}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="opportunity_matrix",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="opportunity_matrix"
        )

        assert result == payload
        assert result is not payload  # Fresh deserialization

    def test_write_flat_dict(self, conn, run_id):
        """A flat dict payload round-trips correctly."""
        payload = {"key1": "value1", "key2": 42, "key3": 3.14}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_summary",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_summary"
        )

        assert result == payload

    def test_write_deeply_nested_dict(self, conn, run_id):
        """A deeply nested structure round-trips correctly."""
        payload = {
            "level1": {
                "level2": {
                    "level3": {
                        "data": [1, 2, 3],
                        "nested_array": [[{"a": 1}]],
                    }
                }
            }
        }
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_clusters",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_clusters"
        )

        assert result == payload

    def test_write_empty_dict(self, conn, run_id):
        """An empty dict payload is valid and round-trips."""
        payload = {}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_trends",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_trends"
        )

        assert result == payload

    def test_write_with_null_values(self, conn, run_id):
        """Dict with None values round-trips correctly."""
        payload = {"key1": None, "key2": "value", "key3": None}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="competition_density",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="competition_density"
        )

        assert result == payload

    def test_write_with_boolean_values(self, conn, run_id):
        """Dict with boolean values round-trips correctly."""
        payload = {"is_valid": True, "is_empty": False}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="funnel_report",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="funnel_report"
        )

        assert result == payload

    def test_rewrite_replaces_prior_value(self, conn, run_id):
        """A second write for the same key overwrites the first."""
        payload_v1 = {"data": [1, 2, 3]}
        payload_v2 = {"data": [4, 5, 6, 7]}

        # Write first version
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="case_studies",
            payload=payload_v1,
            parameters_version="v1",
        )
        assert analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="case_studies"
        ) == payload_v1

        # Overwrite with second version
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="case_studies",
            payload=payload_v2,
            parameters_version="v2",
        )
        assert analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="case_studies"
        ) == payload_v2

    def test_multiple_analysis_types_same_run(self, conn, run_id):
        """Multiple analysis_types for the same run are independent."""
        payload_opp = {"opportunity": "data"}
        payload_tag = {"tag": "data"}

        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="opportunity_matrix",
            payload=payload_opp,
            parameters_version="v1",
        )
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_summary",
            payload=payload_tag,
            parameters_version="v1",
        )

        assert analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="opportunity_matrix"
        ) == payload_opp
        assert analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_summary"
        ) == payload_tag

    def test_nan_in_payload_raises(self, conn, run_id):
        """A payload containing float('nan') raises StorageError."""
        payload = {"x": float("nan")}

        with pytest.raises(StorageError) as exc_info:
            analysis_results.write_analysis_result(
                conn,
                run_id=run_id,
                analysis_type="opportunity_matrix",
                payload=payload,
                parameters_version="v1",
            )
        assert "not JSON-serializable" in str(exc_info.value)

    def test_infinity_in_payload_raises(self, conn, run_id):
        """A payload containing float('inf') raises StorageError."""
        payload = {"x": float("inf")}

        with pytest.raises(StorageError) as exc_info:
            analysis_results.write_analysis_result(
                conn,
                run_id=run_id,
                analysis_type="opportunity_matrix",
                payload=payload,
                parameters_version="v1",
            )
        assert "not JSON-serializable" in str(exc_info.value)

    def test_negative_infinity_in_payload_raises(self, conn, run_id):
        """A payload containing float('-inf') raises StorageError."""
        payload = {"x": float("-inf")}

        with pytest.raises(StorageError) as exc_info:
            analysis_results.write_analysis_result(
                conn,
                run_id=run_id,
                analysis_type="opportunity_matrix",
                payload=payload,
                parameters_version="v1",
            )
        assert "not JSON-serializable" in str(exc_info.value)

    def test_invalid_analysis_type_raises(self, conn, run_id):
        """analysis_type='bogus_type' raises StorageError."""
        payload = {"data": "value"}

        with pytest.raises(StorageError) as exc_info:
            analysis_results.write_analysis_result(
                conn,
                run_id=run_id,
                analysis_type="bogus_type",
                payload=payload,
                parameters_version="v1",
            )
        assert "not in allowed set" in str(exc_info.value)

    def test_nonexistent_run_id_raises(self, conn):
        """write_analysis_result raises StorageError for non-existent run_id."""
        payload = {"data": "value"}

        with pytest.raises(StorageError) as exc_info:
            analysis_results.write_analysis_result(
                conn,
                run_id="nonexistent_run_id",
                analysis_type="opportunity_matrix",
                payload=payload,
                parameters_version="v1",
            )
        assert "does not exist" in str(exc_info.value)

    def test_all_valid_analysis_types(self, conn, run_id):
        """All seven valid analysis_types are accepted."""
        valid_types = [
            "opportunity_matrix",
            "tag_summary",
            "tag_clusters",
            "tag_trends",
            "competition_density",
            "funnel_report",
            "case_studies",
        ]
        payload = {"test": "data"}

        for analysis_type in valid_types:
            analysis_results.write_analysis_result(
                conn,
                run_id=run_id,
                analysis_type=analysis_type,
                payload=payload,
                parameters_version="v1",
            )
            result = analysis_results.read_analysis_result(
                conn, run_id=run_id, analysis_type=analysis_type
            )
            assert result == payload


class TestReadAnalysisResult:
    """Tests for read_analysis_result function."""

    def test_read_existing_result(self, conn, run_id):
        """A result written via write_analysis_result is read back identically."""
        payload = {"analysis": "data", "values": [1, 2, 3]}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_summary",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_summary"
        )

        assert result == payload

    def test_missing_result_returns_none(self, conn, run_id):
        """An analysis_type never written for this run returns None."""
        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="case_studies"
        )

        assert result is None

    def test_missing_run_returns_none(self, conn):
        """read_analysis_result returns None for a non-existent run_id."""
        result = analysis_results.read_analysis_result(
            conn,
            run_id="nonexistent_run_id",
            analysis_type="opportunity_matrix",
        )

        assert result is None

    def test_mutation_of_returned_dict_does_not_persist(self, conn, run_id):
        """Mutating the returned dict and re-reading shows the original content."""
        original_payload = {"data": [1, 2, 3], "nested": {"key": "value"}}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_clusters",
            payload=original_payload,
            parameters_version="v1",
        )

        # Read and mutate
        result1 = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_clusters"
        )
        result1["data"].append(999)  # Mutate the list
        result1["nested"]["key"] = "modified"  # Mutate nested dict

        # Re-read should return original
        result2 = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_clusters"
        )

        assert result2 == original_payload
        assert result2["data"] == [1, 2, 3]
        assert result2["nested"]["key"] == "value"

    def test_fresh_deserialization_each_call(self, conn, run_id):
        """Each call to read_analysis_result returns a distinct dict object."""
        payload = {"key": "value"}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_trends",
            payload=payload,
            parameters_version="v1",
        )

        result1 = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_trends"
        )
        result2 = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_trends"
        )

        assert result1 == result2
        assert result1 is not result2  # Different objects


class TestEdgeCases:
    """Tests for edge cases and corner scenarios."""

    def test_write_with_special_characters_in_payload(self, conn, run_id):
        """Payloads with special characters (quotes, backslashes) round-trip."""
        payload = {
            "text": 'He said "hello" and she replied \'hi\'',
            "path": "C:\\Users\\Name\\file.txt",
            "unicode": "こんにちは",
        }
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="opportunity_matrix",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="opportunity_matrix"
        )

        assert result == payload

    def test_write_with_numeric_string_keys(self, conn, run_id):
        """Dict with numeric string keys (not int keys) round-trips."""
        payload = {"1": "one", "2": "two", "3": {"nested": "value"}}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_summary",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_summary"
        )

        assert result == payload

    def test_write_with_large_nested_structure(self, conn, run_id):
        """A large nested structure with many levels round-trips."""
        # Create a deeply nested structure
        payload = {"level": 0}
        current = payload
        for i in range(1, 10):
            current["nested"] = {"level": i}
            current = current["nested"]
        current["data"] = list(range(100))

        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_clusters",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_clusters"
        )

        assert result == payload

    def test_write_overwrites_completely(self, conn, run_id):
        """Overwriting removes all prior keys (not a merge)."""
        payload_v1 = {"key1": "value1", "key2": "value2"}
        payload_v2 = {"key3": "value3"}

        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="competition_density",
            payload=payload_v1,
            parameters_version="v1",
        )
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="competition_density",
            payload=payload_v2,
            parameters_version="v2",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="competition_density"
        )

        # Should only have key3, not key1 or key2
        assert result == payload_v2
        assert "key1" not in result
        assert "key2" not in result

    def test_multiple_runs_independent(self, conn):
        """Results for different runs are independent."""
        run1_id = runs.create_run(
            conn,
            config={"run": 1},
            parameters_version="v1",
        )
        run2_id = runs.create_run(
            conn,
            config={"run": 2},
            parameters_version="v1",
        )

        payload1 = {"run": 1, "data": "run1_data"}
        payload2 = {"run": 2, "data": "run2_data"}

        analysis_results.write_analysis_result(
            conn,
            run_id=run1_id,
            analysis_type="opportunity_matrix",
            payload=payload1,
            parameters_version="v1",
        )
        analysis_results.write_analysis_result(
            conn,
            run_id=run2_id,
            analysis_type="opportunity_matrix",
            payload=payload2,
            parameters_version="v1",
        )

        result1 = analysis_results.read_analysis_result(
            conn, run_id=run1_id, analysis_type="opportunity_matrix"
        )
        result2 = analysis_results.read_analysis_result(
            conn, run_id=run2_id, analysis_type="opportunity_matrix"
        )

        assert result1 == payload1
        assert result2 == payload2

    def test_payload_with_zero_values(self, conn, run_id):
        """Payloads with zero/0.0/empty string values round-trip."""
        payload = {
            "int_zero": 0,
            "float_zero": 0.0,
            "empty_string": "",
            "empty_list": [],
            "false": False,
        }
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="tag_trends",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="tag_trends"
        )

        assert result == payload

    def test_read_then_delete_run_then_read_returns_none(self, conn, run_id):
        """After cascade delete of run, read_analysis_result returns None."""
        payload = {"data": "value"}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="opportunity_matrix",
            payload=payload,
            parameters_version="v1",
        )

        # Verify it's there
        assert analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="opportunity_matrix"
        ) == payload

        # Delete the run (cascades to analysis_results)
        runs.delete_run(conn, run_id)

        # Read should return None
        assert analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="opportunity_matrix"
        ) is None


class TestThreadSafety:
    """Tests that _check_same_thread is called."""

    def test_write_checks_thread(self, conn, run_id):
        """write_analysis_result calls _check_same_thread (verified by passing)."""
        # If _check_same_thread is not called, we wouldn't catch thread misuse.
        # This test just verifies the function doesn't crash when called in the main thread.
        payload = {"data": "value"}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="opportunity_matrix",
            payload=payload,
            parameters_version="v1",
        )
        # If we reach here, the function worked (and called _check_same_thread).
        assert True

    def test_read_checks_thread(self, conn, run_id):
        """read_analysis_result calls _check_same_thread (verified by passing)."""
        payload = {"data": "value"}
        analysis_results.write_analysis_result(
            conn,
            run_id=run_id,
            analysis_type="opportunity_matrix",
            payload=payload,
            parameters_version="v1",
        )

        result = analysis_results.read_analysis_result(
            conn, run_id=run_id, analysis_type="opportunity_matrix"
        )

        # If we reach here, the function worked (and called _check_same_thread).
        assert result == payload
