"""Tests for benchmark label resolution system."""

from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from etf_pipeline.benchmark_labels import (
    STANDARD_LABEL_ROLE,
    TERSE_LABEL_ROLE,
    _clean_label,
    _extract_label_from_xbrl,
    _get_best_label,
    resolve_benchmark_label,
)
from etf_pipeline.models import BenchmarkMapping


# ---------------------------------------------------------------------------
# _clean_label
# ---------------------------------------------------------------------------


class TestCleanLabel:
    def test_strips_member_suffix_with_space(self):
        assert _clean_label("Bloomberg US Aggregate Bond Index [Member]") == "Bloomberg US Aggregate Bond Index"

    def test_strips_member_suffix_without_space(self):
        # The label ends with '[Member]' but not ' [Member]'
        assert _clean_label("SomeIndex[Member]") == "SomeIndex"

    def test_no_member_suffix_unchanged(self):
        assert _clean_label("S&P 500 Index") == "S&P 500 Index"

    def test_strips_surrounding_whitespace(self):
        assert _clean_label("  S&P 500  ") == "S&P 500"

    def test_strips_whitespace_left_after_member_removal(self):
        # After slicing off '[Member]', a trailing space should be stripped
        assert _clean_label("Bloomberg [Member]") == "Bloomberg"

    def test_empty_string(self):
        assert _clean_label("") == ""


# ---------------------------------------------------------------------------
# _get_best_label
# ---------------------------------------------------------------------------


class TestGetBestLabel:
    def _make_element(self, labels: dict):
        elem = MagicMock()
        elem.labels = labels
        return elem

    def test_prefers_terse_label(self):
        elem = self._make_element({
            TERSE_LABEL_ROLE: "Bloomberg Agg",
            STANDARD_LABEL_ROLE: "Bloomberg US Aggregate Bond Index [Member]",
        })
        assert _get_best_label(elem) == "Bloomberg Agg"

    def test_falls_back_to_standard_label(self):
        elem = self._make_element({
            STANDARD_LABEL_ROLE: "Bloomberg US Aggregate Bond Index [Member]",
        })
        assert _get_best_label(elem) == "Bloomberg US Aggregate Bond Index"

    def test_returns_none_when_no_labels_attr(self):
        elem = object()  # plain object, no .labels attribute
        assert _get_best_label(elem) is None

    def test_returns_none_when_both_labels_missing(self):
        elem = self._make_element({})
        assert _get_best_label(elem) is None

    def test_cleans_terse_label_member_suffix(self):
        elem = self._make_element({
            TERSE_LABEL_ROLE: "S&P 500 [Member]",
        })
        assert _get_best_label(elem) == "S&P 500"


# ---------------------------------------------------------------------------
# _extract_label_from_xbrl
# ---------------------------------------------------------------------------


def _make_xbrl(catalog: dict):
    """Build a minimal mock XBRL object with an element_catalog."""
    xbrl = MagicMock()
    xbrl.element_catalog = catalog
    return xbrl


def _make_catalog_element(terse=None, standard=None):
    """Build a mock element with labels dict."""
    elem = MagicMock()
    labels = {}
    if terse is not None:
        labels[TERSE_LABEL_ROLE] = terse
    if standard is not None:
        labels[STANDARD_LABEL_ROLE] = standard
    elem.labels = labels
    return elem


class TestExtractLabelFromXbrl:
    def test_direct_key_lookup(self):
        elem = _make_catalog_element(terse="Bloomberg Agg")
        xbrl = _make_xbrl({"BloombergUSAggregateBondIndexMember": elem})
        result = _extract_label_from_xbrl(xbrl, "BloombergUSAggregateBondIndexMember")
        assert result == "Bloomberg Agg"

    def test_namespace_prefix_suffix_match(self):
        """ist_BloombergUSAggregateBondIndexMember should match BloombergUSAggregateBondIndexMember."""
        elem = _make_catalog_element(terse="Bloomberg Agg")
        xbrl = _make_xbrl({"ist_BloombergUSAggregateBondIndexMember": elem})
        result = _extract_label_from_xbrl(xbrl, "BloombergUSAggregateBondIndexMember")
        assert result == "Bloomberg Agg"

    def test_returns_none_when_xbrl_is_none(self):
        assert _extract_label_from_xbrl(None, "BloombergUSAggregateBondIndexMember") is None

    def test_returns_none_when_no_element_catalog_attr(self):
        xbrl = object()  # no .element_catalog attribute
        assert _extract_label_from_xbrl(xbrl, "BloombergUSAggregateBondIndexMember") is None

    def test_returns_none_when_catalog_is_not_dict(self):
        xbrl = MagicMock()
        xbrl.element_catalog = "not a dict"
        assert _extract_label_from_xbrl(xbrl, "BloombergUSAggregateBondIndexMember") is None

    def test_returns_none_when_member_id_not_in_catalog(self):
        xbrl = _make_xbrl({"SomeOtherMember": _make_catalog_element(terse="Other")})
        assert _extract_label_from_xbrl(xbrl, "BloombergUSAggregateBondIndexMember") is None

    def test_colon_prefix_matched_as_namespace(self):
        """Colon-prefixed keys are split on ':' to extract bare member_id."""
        elem = _make_catalog_element(terse="Bloomberg Agg")
        xbrl = _make_xbrl({"ist:BloombergUSAggregateBondIndexMember": elem})
        result = _extract_label_from_xbrl(xbrl, "BloombergUSAggregateBondIndexMember")
        assert result == "Bloomberg Agg"

    def test_multiple_prefix_entries_first_match_wins(self):
        elem1 = _make_catalog_element(terse="First Match")
        elem2 = _make_catalog_element(terse="Second Match")
        # dict ordering is insertion-ordered in Python 3.7+
        xbrl = _make_xbrl({
            "abc_BloombergUSAggregateBondIndexMember": elem1,
            "xyz_BloombergUSAggregateBondIndexMember": elem2,
        })
        result = _extract_label_from_xbrl(xbrl, "BloombergUSAggregateBondIndexMember")
        assert result == "First Match"


# ---------------------------------------------------------------------------
# resolve_benchmark_label
# ---------------------------------------------------------------------------


class TestResolveBenchmarkLabel:
    def test_returns_none_for_empty_member_id(self, session):
        assert resolve_benchmark_label(session, "") is None
        assert resolve_benchmark_label(session, None) is None

    def test_cache_hit_returns_cached_label(self, session):
        session.add(BenchmarkMapping(
            member_id="BloombergUSAggregateBondIndexMember",
            readable_name="Bloomberg Agg",
            source="manual",
        ))
        session.flush()

        result = resolve_benchmark_label(session, "BloombergUSAggregateBondIndexMember")
        assert result == "Bloomberg Agg"

    def test_cache_hit_with_null_readable_name_tries_xbrl(self, session):
        """An existing row with readable_name=None should still attempt XBRL extraction."""
        session.add(BenchmarkMapping(
            member_id="BloombergUSAggregateBondIndexMember",
            readable_name=None,
            source=None,
        ))
        session.flush()

        elem = _make_catalog_element(terse="Bloomberg Agg")
        xbrl = _make_xbrl({"BloombergUSAggregateBondIndexMember": elem})

        result = resolve_benchmark_label(
            session, "BloombergUSAggregateBondIndexMember", xbrl_obj=xbrl
        )
        assert result == "Bloomberg Agg"

    def test_cache_miss_extracts_from_xbrl_and_upserts(self, session):
        elem = _make_catalog_element(terse="Bloomberg Agg")
        xbrl = _make_xbrl({"BloombergUSAggregateBondIndexMember": elem})

        result = resolve_benchmark_label(
            session,
            "BloombergUSAggregateBondIndexMember",
            xbrl_obj=xbrl,
            cik="0001234567",
            filing_date=date(2024, 6, 30),
        )
        assert result == "Bloomberg Agg"

        # Verify upserted to DB
        row = session.query(BenchmarkMapping).filter_by(
            member_id="BloombergUSAggregateBondIndexMember"
        ).first()
        assert row is not None
        assert row.readable_name == "Bloomberg Agg"
        assert row.source == "taxonomy_label"
        assert row.first_seen_cik == "0001234567"
        assert row.first_seen_date == date(2024, 6, 30)

    def test_cache_miss_xbrl_failure_records_unmapped_row(self, session):
        """When XBRL extraction fails, member_id is still recorded with readable_name=None."""
        result = resolve_benchmark_label(
            session,
            "UnknownBenchmarkMember",
            xbrl_obj=None,
        )
        assert result is None

        row = session.query(BenchmarkMapping).filter_by(
            member_id="UnknownBenchmarkMember"
        ).first()
        assert row is not None
        assert row.readable_name is None
        assert row.source is None

    def test_cache_miss_existing_null_row_updated_on_xbrl_hit(self, session):
        """An existing null-readable_name row gets updated when XBRL extraction succeeds."""
        session.add(BenchmarkMapping(
            member_id="BloombergUSAggregateBondIndexMember",
            readable_name=None,
            source=None,
        ))
        session.flush()

        elem = _make_catalog_element(standard="Bloomberg US Aggregate Bond Index [Member]")
        xbrl = _make_xbrl({"BloombergUSAggregateBondIndexMember": elem})

        result = resolve_benchmark_label(
            session, "BloombergUSAggregateBondIndexMember", xbrl_obj=xbrl
        )
        assert result == "Bloomberg US Aggregate Bond Index"

        row = session.query(BenchmarkMapping).filter_by(
            member_id="BloombergUSAggregateBondIndexMember"
        ).first()
        assert row.readable_name == "Bloomberg US Aggregate Bond Index"
        assert row.source == "taxonomy_label"

    def test_second_lookup_of_unmapped_does_not_duplicate_row(self, session):
        """Calling resolve twice for an unresolvable member_id should not add a second row."""
        resolve_benchmark_label(session, "UnknownBenchmarkMember", xbrl_obj=None)
        resolve_benchmark_label(session, "UnknownBenchmarkMember", xbrl_obj=None)

        rows = session.query(BenchmarkMapping).filter_by(
            member_id="UnknownBenchmarkMember"
        ).all()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# BenchmarkMapping model CRUD
# ---------------------------------------------------------------------------


class TestBenchmarkMappingModel:
    def test_create_and_query(self, session):
        mapping = BenchmarkMapping(
            member_id="SP500Member",
            readable_name="S&P 500",
            source="manual",
            first_seen_cik="0001234567",
            first_seen_date=date(2024, 1, 1),
        )
        session.add(mapping)
        session.flush()

        row = session.query(BenchmarkMapping).filter_by(member_id="SP500Member").first()
        assert row is not None
        assert row.readable_name == "S&P 500"
        assert row.source == "manual"
        assert row.first_seen_cik == "0001234567"
        assert row.first_seen_date == date(2024, 1, 1)
        assert row.id is not None

    def test_unique_constraint_on_member_id(self, session):
        session.add(BenchmarkMapping(member_id="SP500Member", readable_name="S&P 500"))
        session.flush()

        session.add(BenchmarkMapping(member_id="SP500Member", readable_name="Duplicate"))
        with pytest.raises(IntegrityError):
            session.flush()

    def test_nullable_fields_allowed(self, session):
        mapping = BenchmarkMapping(
            member_id="NullableMember",
            readable_name=None,
            source=None,
            first_seen_cik=None,
            first_seen_date=None,
        )
        session.add(mapping)
        session.flush()

        row = session.query(BenchmarkMapping).filter_by(member_id="NullableMember").first()
        assert row is not None
        assert row.readable_name is None
        assert row.source is None

    def test_update_readable_name(self, session):
        mapping = BenchmarkMapping(member_id="UpdateMember", readable_name=None)
        session.add(mapping)
        session.flush()

        mapping.readable_name = "Updated Label"
        session.flush()

        row = session.query(BenchmarkMapping).filter_by(member_id="UpdateMember").first()
        assert row.readable_name == "Updated Label"
