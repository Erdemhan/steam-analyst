"""Unit tests for reporting.types module."""

import pytest

from steam_analyst.reporting.types import (
    Caveat,
    CaseStudySelection,
    ReportNotAvailable,
    FunnelSummary,
)


class TestCaveat:
    """Tests for Caveat dataclass."""

    def test_caveat_creation_with_info_severity(self):
        """A Caveat with severity='info' can be created."""
        caveat = Caveat(
            key="steamspy_owner_confidence",
            title="SteamSpy Owner Estimates",
            body="SteamSpy owner estimates are low-confidence approximations.",
            severity="info",
        )
        assert caveat.key == "steamspy_owner_confidence"
        assert caveat.severity == "info"

    def test_caveat_creation_with_warning_severity(self):
        """A Caveat with severity='warning' can be created."""
        caveat = Caveat(
            key="coarse_filter_boundary",
            title="Coarse Filter Boundary",
            body="The coarse filter is a hard boundary.",
            severity="warning",
        )
        assert caveat.key == "coarse_filter_boundary"
        assert caveat.severity == "warning"

    def test_caveat_is_frozen(self):
        """A Caveat instance is immutable (frozen dataclass)."""
        caveat = Caveat(
            key="test_key",
            title="Test Title",
            body="Test body",
            severity="info",
        )
        with pytest.raises(AttributeError):
            caveat.key = "modified"

    def test_caveat_equality(self):
        """Two Caveats with identical fields are equal."""
        caveat1 = Caveat(
            key="test", title="Title", body="Body", severity="info"
        )
        caveat2 = Caveat(
            key="test", title="Title", body="Body", severity="info"
        )
        assert caveat1 == caveat2

    def test_caveat_inequality_on_key(self):
        """Two Caveats with different keys are not equal."""
        caveat1 = Caveat(
            key="key1", title="Title", body="Body", severity="info"
        )
        caveat2 = Caveat(
            key="key2", title="Title", body="Body", severity="info"
        )
        assert caveat1 != caveat2

    def test_caveat_severity_constrained(self):
        """Caveat instances can be created with severity in {'info', 'warning'}."""
        valid_severities = ["info", "warning"]
        for severity in valid_severities:
            caveat = Caveat(
                key="test",
                title="Test",
                body="Test body",
                severity=severity,
            )
            assert caveat.severity == severity

    def test_caveat_with_archetype_cap_relaxed_key(self):
        """A Caveat with the dynamic 'archetype_cap_relaxed' key can be created."""
        caveat = Caveat(
            key="archetype_cap_relaxed",
            title="Archetype Cap Relaxed",
            body="The archetype diversity cap was relaxed to reach the target case study count.",
            severity="info",
        )
        assert caveat.key == "archetype_cap_relaxed"

    def test_caveat_known_limitation_keys(self):
        """Caveats can be created with all known limitation keys."""
        known_keys = [
            "steamspy_owner_confidence",
            "boxleiter_approximation",
            "simplicity_proxy",
            "no_scraping_demand_gap",
            "survivorship_bias",
            "competition_historical",
            "coarse_filter_boundary",
        ]
        for key in known_keys:
            caveat = Caveat(
                key=key, title="Title", body="Body", severity="info"
            )
            assert caveat.key == key


class TestReportNotAvailable:
    """Tests for ReportNotAvailable exception."""

    def test_reportnotavailable_can_be_raised(self):
        """ReportNotAvailable can be raised with a message."""
        with pytest.raises(ReportNotAvailable):
            raise ReportNotAvailable("run_123")

    def test_reportnotavailable_message_contains_run_id(self):
        """ReportNotAvailable message contains the run_id that was not found."""
        run_id = "test_run_001"
        with pytest.raises(ReportNotAvailable) as exc_info:
            raise ReportNotAvailable(run_id)
        assert run_id in str(exc_info.value)

    def test_reportnotavailable_with_descriptive_message(self):
        """ReportNotAvailable can carry a descriptive error message."""
        message = "Run 'nonexistent_run' does not exist"
        with pytest.raises(ReportNotAvailable) as exc_info:
            raise ReportNotAvailable(message)
        assert "nonexistent_run" in str(exc_info.value)

    def test_reportnotavailable_is_exception_subclass(self):
        """ReportNotAvailable is a subclass of Exception."""
        exc = ReportNotAvailable("test")
        assert isinstance(exc, Exception)


class TestFunnelSummary:
    """Tests for FunnelSummary dataclass."""

    def test_funnel_summary_creation(self):
        """A FunnelSummary can be created with all fields."""
        funnel = FunnelSummary(
            catalog_size=150000,
            candidate_count=5000,
            detail_fetched=4800,
            detail_failed=200,
            simple_subset_size=2500,
            rejected_by_reason={
                "coarse_filter.review_count_below_floor": 100000,
                "coarse_filter.release_too_recent": 40000,
                "simplicity_filter.above_simplicity_threshold": 2500,
            },
        )
        assert funnel.catalog_size == 150000
        assert funnel.candidate_count == 5000
        assert funnel.detail_fetched == 4800
        assert funnel.detail_failed == 200
        assert funnel.simple_subset_size == 2500
        assert len(funnel.rejected_by_reason) == 3

    def test_funnel_summary_ordering_invariant(self):
        """For a normal run, simple_subset_size <= candidate_count <= catalog_size."""
        funnel = FunnelSummary(
            catalog_size=150000,
            candidate_count=5000,
            detail_fetched=4500,
            detail_failed=500,
            simple_subset_size=2500,
            rejected_by_reason={},
        )
        assert funnel.simple_subset_size <= funnel.candidate_count
        assert funnel.candidate_count <= funnel.catalog_size

    def test_funnel_summary_edge_case_all_zeros(self):
        """A FunnelSummary with all zeros (incomplete run) is valid."""
        funnel = FunnelSummary(
            catalog_size=0,
            candidate_count=0,
            detail_fetched=0,
            detail_failed=0,
            simple_subset_size=0,
            rejected_by_reason={},
        )
        assert funnel.catalog_size == 0
        assert funnel.candidate_count == 0
        assert funnel.simple_subset_size == 0

    def test_funnel_summary_edge_case_no_filtering(self):
        """An implausibly permissive coarse filter (candidate_count == catalog_size) is rendered as-is."""
        funnel = FunnelSummary(
            catalog_size=150000,
            candidate_count=150000,
            detail_fetched=150000,
            detail_failed=0,
            simple_subset_size=100000,
            rejected_by_reason={},
        )
        assert funnel.candidate_count == funnel.catalog_size
        # Reporting does not second-guess or reject unusual funnels

    def test_funnel_summary_is_frozen(self):
        """A FunnelSummary instance is immutable (frozen dataclass)."""
        funnel = FunnelSummary(
            catalog_size=100,
            candidate_count=50,
            detail_fetched=45,
            detail_failed=5,
            simple_subset_size=25,
            rejected_by_reason={},
        )
        with pytest.raises(AttributeError):
            funnel.catalog_size = 200

    def test_funnel_summary_rejected_by_reason_prefixed_keys(self):
        """Rejected reasons have stage-specific prefixes ('coarse_filter.' or 'simplicity_filter.')."""
        funnel = FunnelSummary(
            catalog_size=1000,
            candidate_count=100,
            detail_fetched=100,
            detail_failed=0,
            simple_subset_size=50,
            rejected_by_reason={
                "coarse_filter.review_count_below_floor": 500,
                "coarse_filter.price_out_of_range": 300,
                "simplicity_filter.above_simplicity_threshold": 50,
            },
        )
        # Verify prefixes are present
        for key in funnel.rejected_by_reason.keys():
            assert key.startswith("coarse_filter.") or key.startswith(
                "simplicity_filter."
            )

    def test_funnel_summary_detail_fetch_statistics(self):
        """detail_fetched and detail_failed track per-app fetch coverage."""
        funnel = FunnelSummary(
            catalog_size=10000,
            candidate_count=1000,
            detail_fetched=950,  # 95% success
            detail_failed=50,   # 5% failure
            simple_subset_size=700,
            rejected_by_reason={"simplicity_filter.above_simplicity_threshold": 300},
        )
        # A large detail_failed signals degraded but succeeded acquisition
        assert funnel.detail_fetched + funnel.detail_failed == funnel.candidate_count

    def test_funnel_summary_equality(self):
        """Two FunnelSummaries with identical fields are equal."""
        funnel1 = FunnelSummary(
            catalog_size=100,
            candidate_count=50,
            detail_fetched=45,
            detail_failed=5,
            simple_subset_size=25,
            rejected_by_reason={"coarse_filter.test": 25},
        )
        funnel2 = FunnelSummary(
            catalog_size=100,
            candidate_count=50,
            detail_fetched=45,
            detail_failed=5,
            simple_subset_size=25,
            rejected_by_reason={"coarse_filter.test": 25},
        )
        assert funnel1 == funnel2


class TestCaseStudySelection:
    """Tests for CaseStudySelection dataclass."""

    def test_case_study_selection_creation_empty(self):
        """A CaseStudySelection can be created with an empty case_studies list."""
        selection = CaseStudySelection(
            case_studies=[],
            archetype_cap_relaxed=False,
        )
        assert selection.case_studies == []
        assert selection.archetype_cap_relaxed is False

    def test_case_study_selection_with_cap_not_relaxed(self):
        """A CaseStudySelection with archetype_cap_relaxed=False indicates no relaxation occurred."""
        selection = CaseStudySelection(
            case_studies=[],  # Would normally contain CaseStudy objects
            archetype_cap_relaxed=False,
        )
        assert selection.archetype_cap_relaxed is False

    def test_case_study_selection_with_cap_relaxed(self):
        """A CaseStudySelection with archetype_cap_relaxed=True indicates the cap was relaxed."""
        selection = CaseStudySelection(
            case_studies=[],
            archetype_cap_relaxed=True,
        )
        assert selection.archetype_cap_relaxed is True

    def test_case_study_selection_archetype_cap_relaxed_flag_is_boolean(self):
        """The archetype_cap_relaxed field is a boolean."""
        selection_true = CaseStudySelection(
            case_studies=[], archetype_cap_relaxed=True
        )
        selection_false = CaseStudySelection(
            case_studies=[], archetype_cap_relaxed=False
        )
        assert isinstance(selection_true.archetype_cap_relaxed, bool)
        assert isinstance(selection_false.archetype_cap_relaxed, bool)

    def test_case_study_selection_case_studies_is_list(self):
        """The case_studies field is always a list."""
        selection = CaseStudySelection(
            case_studies=[],
            archetype_cap_relaxed=False,
        )
        assert isinstance(selection.case_studies, list)

    def test_case_study_selection_equality(self):
        """Two CaseStudySelections with identical fields are equal."""
        selection1 = CaseStudySelection(
            case_studies=[],
            archetype_cap_relaxed=False,
        )
        selection2 = CaseStudySelection(
            case_studies=[],
            archetype_cap_relaxed=False,
        )
        assert selection1 == selection2

    def test_case_study_selection_inequality_on_relaxed_flag(self):
        """Two CaseStudySelections differing only in archetype_cap_relaxed are not equal."""
        selection1 = CaseStudySelection(
            case_studies=[],
            archetype_cap_relaxed=False,
        )
        selection2 = CaseStudySelection(
            case_studies=[],
            archetype_cap_relaxed=True,
        )
        assert selection1 != selection2
