"""Tests for N-CSR parser."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from sqlalchemy import select

from etf_pipeline.models import ETF, Performance
from etf_pipeline.parsers.ncsr import (
    _calculate_period_years,
    _extract_class_id,
    _map_return_period,
    _parse_decimal,
    parse_ncsr,
)


@pytest.fixture
def sample_etfs_with_class_id(session):
    """Create sample ETFs with class_id in the database."""
    etfs = [
        ETF(
            ticker="IVV",
            cik="0001100663",
            series_id="S000002809",
            class_id="C000131291",
            issuer_name="iShares Trust",
            fund_name="iShares Core S&P 500 ETF",
        ),
        ETF(
            ticker="IJH",
            cik="0001100663",
            series_id="S000002810",
            class_id="C000131292",
            issuer_name="iShares Trust",
            fund_name="iShares Core S&P Mid-Cap ETF",
        ),
        ETF(
            ticker="VOO",
            cik="0000036405",
            series_id="S000002839",
            class_id="C000002839",
            issuer_name="Vanguard Group Inc",
            fund_name="Vanguard S&P 500 ETF",
        ),
    ]
    for etf in etfs:
        session.add(etf)
    session.commit()
    return etfs


class TestClassIdExtraction:
    """Test class_id extraction from ClassAxis member values."""

    def test_extract_with_namespace_and_suffix(self):
        """Test extraction with namespace prefix and Member suffix."""
        assert _extract_class_id("ist:C000131291Member") == "C000131291"

    def test_extract_without_namespace(self):
        """Test extraction without namespace prefix."""
        assert _extract_class_id("C000131291Member") == "C000131291"

    def test_extract_none(self):
        """Test extraction with None input."""
        assert _extract_class_id(None) is None

    def test_extract_empty_string(self):
        """Test extraction with empty string."""
        assert _extract_class_id("") is None

    def test_extract_non_string(self):
        """Test extraction with non-string input."""
        assert _extract_class_id(123) is None


class TestPeriodMapping:
    """Test return period mapping from date ranges."""

    def test_map_1yr_period(self):
        """Test 1-year period mapping."""
        start = date(2023, 10, 31)
        end = date(2024, 10, 31)
        assert _map_return_period(start, end) == "return_1yr"

    def test_map_1yr_period_with_tolerance(self):
        """Test 1-year period with +/- 30 day tolerance."""
        start = date(2023, 10, 31)
        end = date(2024, 11, 15)  # 15 days over
        assert _map_return_period(start, end) == "return_1yr"

        end = date(2024, 10, 15)  # 16 days under
        assert _map_return_period(start, end) == "return_1yr"

    def test_map_5yr_period(self):
        """Test 5-year period mapping."""
        start = date(2019, 10, 31)
        end = date(2024, 10, 31)
        assert _map_return_period(start, end) == "return_5yr"

    def test_map_10yr_period(self):
        """Test 10-year period mapping."""
        start = date(2014, 10, 31)
        end = date(2024, 10, 31)
        assert _map_return_period(start, end) == "return_10yr"

    def test_map_since_inception(self):
        """Test since inception mapping (non-standard period)."""
        start = date(2020, 3, 15)
        end = date(2024, 10, 31)
        assert _map_return_period(start, end) == "return_since_inception"

    def test_map_with_none_dates(self):
        """Test mapping with None dates."""
        assert _map_return_period(None, date(2024, 10, 31)) is None
        assert _map_return_period(date(2023, 10, 31), None) is None
        assert _map_return_period(None, None) is None

    def test_calculate_period_years(self):
        """Test year calculation."""
        start = date(2023, 10, 31)
        end = date(2024, 10, 31)
        years = _calculate_period_years(start, end)
        assert years is not None
        assert abs(years - 1.0) < 0.01


class TestDecimalParsing:
    """Test decimal parsing helper."""

    def test_parse_decimal_from_decimal(self):
        """Test parsing from Decimal."""
        assert _parse_decimal(Decimal("0.05")) == Decimal("0.05")

    def test_parse_decimal_from_float(self):
        """Test parsing from float."""
        result = _parse_decimal(0.05)
        assert result is not None
        assert abs(result - Decimal("0.05")) < Decimal("0.0001")

    def test_parse_decimal_from_string(self):
        """Test parsing from string."""
        assert _parse_decimal("0.05") == Decimal("0.05")

    def test_parse_decimal_from_int(self):
        """Test parsing from int."""
        assert _parse_decimal(5) == Decimal("5")

    def test_parse_decimal_from_none(self):
        """Test parsing from None."""
        assert _parse_decimal(None) is None

    def test_parse_decimal_from_invalid(self):
        """Test parsing from invalid value."""
        assert _parse_decimal("invalid") is None


class TestNCSRParser:
    """Test N-CSR parser integration."""

    @pytest.fixture
    def mock_xbrl_dataframe(self):
        """Create a mock XBRL DataFrame with sample N-CSR data."""
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:ExpenseRatioPct',
                'us-gaap:InvestmentCompanyPortfolioTurnover',
                # Benchmark returns
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
            ],
            'numeric_value': [
                Decimal('0.1234'),  # 1yr fund return
                Decimal('0.0850'),  # 5yr fund return
                Decimal('0.0920'),  # 10yr fund return
                Decimal('0.0003'),  # expense ratio
                Decimal('0.15'),    # portfolio turnover
                Decimal('0.1100'),  # 1yr benchmark return
                Decimal('0.0800'),  # 5yr benchmark return
                Decimal('0.0880'),  # 10yr benchmark return
            ],
            'period_start': [
                date(2023, 10, 31),
                date(2019, 10, 31),
                date(2014, 10, 31),
                None,
                None,
                date(2023, 10, 31),
                date(2019, 10, 31),
                date(2014, 10, 31),
            ],
            'period_end': [
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
            ],
            'dim_oef_ClassAxis': [
                'ist:C000131291Member',
                'ist:C000131291Member',
                'ist:C000131291Member',
                'ist:C000131291Member',
                'ist:C000131291Member',
                None,  # Benchmark rows have NULL ClassAxis (matches real XBRL)
                None,
                None,
            ],
            'dim_oef_BroadBasedIndexAxis': [
                None,  # Fund returns have NaN benchmark axis
                None,
                None,
                None,
                None,
                'ist:BloombergUSUniversalIndexMember',  # Benchmark returns
                'ist:BloombergUSUniversalIndexMember',
                'ist:BloombergUSUniversalIndexMember',
            ],
        }
        return pd.DataFrame(data)

    @pytest.fixture
    def mock_edgar_ncsr(self, mock_xbrl_dataframe):
        """Mock edgar Company and filing for N-CSR."""
        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            # Mock filing
            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True

            # Mock XBRL object
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = mock_xbrl_dataframe
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            # Mock filings collection
            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            yield mock_class

    def test_parse_ncsr_success(
        self, session, sample_etfs_with_class_id, mock_edgar_ncsr, mock_ncsr_db
    ):
        """Test successful N-CSR parsing."""
        parse_ncsr(cik="0001100663", clear_cache=False)

        # Verify Performance records were created
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        assert perf.fiscal_year_end == date(2024, 10, 31)
        assert perf.return_1yr == Decimal('0.1234')
        assert perf.return_5yr == Decimal('0.0850')
        assert perf.return_10yr == Decimal('0.0920')
        assert perf.expense_ratio_actual == Decimal('0.0003')
        assert perf.portfolio_turnover == Decimal('0.15')
        # Verify benchmark data
        assert perf.benchmark_name == "BloombergUSUniversalIndexMember"
        assert perf.benchmark_return_1yr == Decimal('0.1100')
        assert perf.benchmark_return_5yr == Decimal('0.0800')
        assert perf.benchmark_return_10yr == Decimal('0.0880')

    def test_parse_ncsr_no_filings(self, session, sample_etfs_with_class_id, mock_ncsr_db):
        """Test N-CSR parsing when no filings exist."""
        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            mock_instance.get_filings.return_value = []

            parse_ncsr(cik="0001100663", clear_cache=False)

            # Should not error, no performance records created
            stmt = select(Performance)
            results = session.execute(stmt).scalars().all()
            assert len(results) == 0

    def test_parse_ncsr_not_ixbrl(self, session, sample_etfs_with_class_id, mock_ncsr_db):
        """Test N-CSR parsing when filing is not inline XBRL."""
        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = False
            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

            # Should skip, no performance records created
            stmt = select(Performance)
            results = session.execute(stmt).scalars().all()
            assert len(results) == 0

    def test_parse_ncsr_class_id_not_found(self, session, mock_ncsr_db):
        """Test N-CSR parsing when class_id not in database."""
        # Create ETF without matching class_id
        etf = ETF(
            ticker="IVV",
            cik="0001100663",
            series_id="S000002809",
            class_id="C000000000",  # Different class_id
            issuer_name="iShares Trust",
            fund_name="iShares Core S&P 500 ETF",
        )
        session.add(etf)
        session.commit()

        # Mock with XBRL data for different class_id
        data = {
            'concept': ['oef:AvgAnnlRtrPct'],
            'numeric_value': [Decimal('0.1234')],
            'period_start': [date(2023, 10, 31)],
            'period_end': [date(2024, 10, 31)],
            'dim_oef_ClassAxis': ['ist:C000131291Member'],  # Won't match
            'dim_oef_BroadBasedIndexAxis': [None],
        }
        mock_df = pd.DataFrame(data)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = mock_df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

            # Should skip mismatched class_id, no performance records created
            stmt = select(Performance)
            results = session.execute(stmt).scalars().all()
            assert len(results) == 0

    def test_parse_ncsr_upsert(
        self, session, sample_etfs_with_class_id, mock_edgar_ncsr, mock_ncsr_db
    ):
        """Test N-CSR parser upsert behavior."""
        # First parse
        parse_ncsr(cik="0001100663", clear_cache=False)

        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()
        assert perf is not None
        original_id = perf.id

        # Second parse with updated data
        updated_df = pd.DataFrame({
            'concept': ['oef:AvgAnnlRtrPct'],
            'numeric_value': [Decimal('0.2000')],  # Different value
            'period_start': [date(2023, 10, 31)],
            'period_end': [date(2024, 10, 31)],
            'dim_oef_ClassAxis': ['ist:C000131291Member'],
            'dim_oef_BroadBasedIndexAxis': [None],
        })

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = updated_df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        # Refresh session to get updated data
        session.expire_all()
        perf_updated = session.execute(stmt).scalar_one_or_none()
        assert perf_updated is not None
        assert perf_updated.id == original_id  # Same record
        assert perf_updated.return_1yr == Decimal('0.2000')  # Updated value

    def test_parse_ncsr_with_benchmark(self, session, sample_etfs_with_class_id, mock_ncsr_db):
        """Test N-CSR parsing with benchmark data."""
        # Create mock data with benchmark
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
            ],
            'numeric_value': [
                Decimal('0.1234'),  # 1yr fund return
                Decimal('0.1100'),  # 1yr benchmark return
                Decimal('0.0800'),  # 5yr benchmark return
            ],
            'period_start': [
                date(2023, 10, 31),
                date(2023, 10, 31),
                date(2019, 10, 31),
            ],
            'period_end': [
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
            ],
            'dim_oef_ClassAxis': [
                'ist:C000131291Member',
                None,  # Benchmark rows have NULL ClassAxis (matches real XBRL)
                None,
            ],
            'dim_oef_BroadBasedIndexAxis': [
                None,
                'ist:SP500IndexMember',
                'ist:SP500IndexMember',
            ],
        }
        mock_df = pd.DataFrame(data)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = mock_df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        # Verify benchmark data was extracted
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        assert perf.benchmark_name == "SP500IndexMember"
        assert perf.benchmark_return_1yr == Decimal('0.1100')
        assert perf.benchmark_return_5yr == Decimal('0.0800')
        assert perf.benchmark_return_10yr is None  # Not provided

    def test_parse_ncsr_no_benchmark(self, session, sample_etfs_with_class_id, mock_ncsr_db):
        """Test N-CSR parsing when no benchmark data exists."""
        # Create mock data without benchmark
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
            ],
            'numeric_value': [
                Decimal('0.1234'),  # 1yr fund return
                Decimal('0.0850'),  # 5yr fund return
            ],
            'period_start': [
                date(2023, 10, 31),
                date(2019, 10, 31),
            ],
            'period_end': [
                date(2024, 10, 31),
                date(2024, 10, 31),
            ],
            'dim_oef_ClassAxis': [
                'ist:C000131291Member',
                'ist:C000131291Member',
            ],
            'dim_oef_BroadBasedIndexAxis': [
                None,
                None,
            ],
        }
        mock_df = pd.DataFrame(data)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = mock_df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        # Verify benchmark fields are NULL
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        assert perf.return_1yr == Decimal('0.1234')
        assert perf.return_5yr == Decimal('0.0850')
        assert perf.benchmark_name is None
        assert perf.benchmark_return_1yr is None
        assert perf.benchmark_return_5yr is None
        assert perf.benchmark_return_10yr is None

    def test_parse_ncsr_multiple_filings_different_class_ids(
        self, session, sample_etfs_with_class_id, mock_ncsr_db
    ):
        """Test that parser iterates multiple filings to find different class_ids.

        Simulates Vanguard-style filing where each N-CSR covers a different
        fund series (class_id) under the same CIK.
        """
        # Filing 1: contains data for C000131291 (IVV)
        df_filing1 = pd.DataFrame({
            'concept': ['oef:AvgAnnlRtrPct', 'oef:ExpenseRatioPct'],
            'numeric_value': [Decimal('0.1234'), Decimal('0.0003')],
            'period_start': [date(2023, 10, 31), None],
            'period_end': [date(2024, 10, 31), date(2024, 10, 31)],
            'dim_oef_ClassAxis': [
                'ist:C000131291Member',
                'ist:C000131291Member',
            ],
            'dim_oef_BroadBasedIndexAxis': [None, None],
        })

        # Filing 2: contains data for C000131292 (IJH)
        df_filing2 = pd.DataFrame({
            'concept': ['oef:AvgAnnlRtrPct', 'oef:ExpenseRatioPct'],
            'numeric_value': [Decimal('0.0950'), Decimal('0.0005')],
            'period_start': [date(2023, 10, 31), None],
            'period_end': [date(2024, 10, 31), date(2024, 10, 31)],
            'dim_oef_ClassAxis': [
                'ist:C000131292Member',
                'ist:C000131292Member',
            ],
            'dim_oef_BroadBasedIndexAxis': [None, None],
        })

        def _make_mock_filing(df):
            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl
            return mock_filing

        filing1 = _make_mock_filing(df_filing1)
        filing2 = _make_mock_filing(df_filing2)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filings = Mock()
            all_filings = [filing1, filing2]
            mock_filings.__getitem__ = Mock(side_effect=lambda i: all_filings[i])
            mock_filings.__len__ = Mock(return_value=2)
            mock_filings.__bool__ = Mock(return_value=True)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        # Verify IVV got performance from filing 1
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf_ivv = session.execute(stmt).scalar_one_or_none()
        assert perf_ivv is not None
        assert perf_ivv.return_1yr == Decimal('0.1234')
        assert perf_ivv.expense_ratio_actual == Decimal('0.0003')

        # Verify IJH got performance from filing 2
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[1].id
        )
        perf_ijh = session.execute(stmt).scalar_one_or_none()
        assert perf_ijh is not None
        assert perf_ijh.return_1yr == Decimal('0.0950')
        assert perf_ijh.expense_ratio_actual == Decimal('0.0005')

    def test_parse_ncsr_first_match_wins(
        self, session, sample_etfs_with_class_id, mock_ncsr_db
    ):
        """Test that the first filing's data wins for the same class_id + fiscal_year_end."""
        # Filing 1: C000131291 with return 0.1234
        df_filing1 = pd.DataFrame({
            'concept': ['oef:AvgAnnlRtrPct'],
            'numeric_value': [Decimal('0.1234')],
            'period_start': [date(2023, 10, 31)],
            'period_end': [date(2024, 10, 31)],
            'dim_oef_ClassAxis': ['ist:C000131291Member'],
            'dim_oef_BroadBasedIndexAxis': [None],
        })

        # Filing 2: same C000131291 with different return 0.9999
        df_filing2 = pd.DataFrame({
            'concept': ['oef:AvgAnnlRtrPct'],
            'numeric_value': [Decimal('0.9999')],
            'period_start': [date(2023, 10, 31)],
            'period_end': [date(2024, 10, 31)],
            'dim_oef_ClassAxis': ['ist:C000131291Member'],
            'dim_oef_BroadBasedIndexAxis': [None],
        })

        def _make_mock_filing(df):
            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl
            return mock_filing

        filing1 = _make_mock_filing(df_filing1)
        filing2 = _make_mock_filing(df_filing2)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filings = Mock()
            all_filings = [filing1, filing2]
            mock_filings.__getitem__ = Mock(side_effect=lambda i: all_filings[i])
            mock_filings.__len__ = Mock(return_value=2)
            mock_filings.__bool__ = Mock(return_value=True)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        # First filing's value should win
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()
        assert perf is not None
        assert perf.return_1yr == Decimal('0.1234')  # First filing wins, not 0.9999

    def test_parse_ncsr_skips_failed_xbrl_continues(
        self, session, sample_etfs_with_class_id, mock_ncsr_db
    ):
        """Test that a filing with failed XBRL is skipped and the next filing is tried."""
        # Filing 1: XBRL fails
        mock_filing1 = Mock()
        mock_filing1.is_inline_xbrl = True
        mock_filing1.filing_date = date(2024, 12, 1)
        mock_filing1.xbrl.side_effect = Exception("XBRL parse error")

        # Filing 2: succeeds with C000131291 data
        df_filing2 = pd.DataFrame({
            'concept': ['oef:AvgAnnlRtrPct'],
            'numeric_value': [Decimal('0.0777')],
            'period_start': [date(2023, 10, 31)],
            'period_end': [date(2024, 10, 31)],
            'dim_oef_ClassAxis': ['ist:C000131291Member'],
            'dim_oef_BroadBasedIndexAxis': [None],
        })
        mock_filing2 = Mock()
        mock_filing2.is_inline_xbrl = True
        mock_filing2.filing_date = date(2024, 12, 1)
        mock_xbrl2 = Mock()
        mock_facts2 = Mock()
        mock_facts2.to_dataframe.return_value = df_filing2
        mock_xbrl2.facts = mock_facts2
        mock_filing2.xbrl.return_value = mock_xbrl2

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filings = Mock()
            all_filings = [mock_filing1, mock_filing2]
            mock_filings.__getitem__ = Mock(side_effect=lambda i: all_filings[i])
            mock_filings.__len__ = Mock(return_value=2)
            mock_filings.__bool__ = Mock(return_value=True)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        # Data from filing 2 should be present
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()
        assert perf is not None
        assert perf.return_1yr == Decimal('0.0777')

    def test_parse_ncsr_writes_processing_log(
        self, session, sample_etfs_with_class_id, mock_edgar_ncsr, mock_ncsr_db
    ):
        """Test that parse_ncsr writes ProcessingLog row with correct data."""
        from etf_pipeline.models import ProcessingLog

        parse_ncsr(cik="0001100663", clear_cache=False)

        # Verify ProcessingLog was created
        stmt = select(ProcessingLog).where(
            ProcessingLog.cik == "0001100663",
            ProcessingLog.parser_type == "ncsr"
        )
        log = session.execute(stmt).scalar_one_or_none()

        assert log is not None
        assert log.cik == "0001100663"
        assert log.parser_type == "ncsr"
        assert log.latest_filing_date_seen == date(2024, 12, 1)
        assert log.last_run_at is not None

    def test_parse_ncsr_sets_filing_date(
        self, session, sample_etfs_with_class_id, mock_edgar_ncsr, mock_ncsr_db
    ):
        """Test that parse_ncsr sets filing_date on inserted Performance rows."""
        parse_ncsr(cik="0001100663", clear_cache=False)

        # Verify Performance has filing_date
        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one()
        assert perf.filing_date == date(2024, 12, 1)

    def test_benchmark_additional_index_fallback(
        self, session, sample_etfs_with_class_id, mock_ncsr_db
    ):
        """Benchmark is extracted from AdditionalIndexAxis when BroadBasedIndexAxis is absent."""
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:ExpenseRatioPct',
                # AdditionalIndexAxis benchmark rows (ClassAxis is NULL)
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
            ],
            'numeric_value': [
                Decimal('0.1500'),  # 1yr fund return
                Decimal('0.0900'),  # 5yr fund return
                Decimal('0.1000'),  # 10yr fund return
                Decimal('0.0004'),  # expense ratio
                Decimal('0.1400'),  # 1yr benchmark return
                Decimal('0.0850'),  # 5yr benchmark return
                Decimal('0.0950'),  # 10yr benchmark return
            ],
            'period_start': [
                date(2023, 10, 31),
                date(2019, 10, 31),
                date(2014, 10, 31),
                None,
                date(2023, 10, 31),
                date(2019, 10, 31),
                date(2014, 10, 31),
            ],
            'period_end': [
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
            ],
            'dim_oef_ClassAxis': [
                'ist:C000131291Member',
                'ist:C000131291Member',
                'ist:C000131291Member',
                'ist:C000131291Member',
                None,  # Benchmark rows have NULL ClassAxis
                None,
                None,
            ],
            # No BroadBasedIndexAxis column at all — only AdditionalIndexAxis
            'dim_oef_AdditionalIndexAxis': [
                None,  # Fund rows have NULL AdditionalIndexAxis
                None,
                None,
                None,
                'ist:RussellMidcapIndexMember',  # Benchmark rows
                'ist:RussellMidcapIndexMember',
                'ist:RussellMidcapIndexMember',
            ],
        }
        mock_df = pd.DataFrame(data)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = mock_df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        # Fund returns are present
        assert perf.return_1yr == Decimal('0.1500')
        assert perf.return_5yr == Decimal('0.0900')
        assert perf.return_10yr == Decimal('0.1000')
        # Benchmark came from AdditionalIndexAxis fallback
        assert perf.benchmark_name == "RussellMidcapIndexMember"
        assert perf.benchmark_return_1yr == Decimal('0.1400')
        assert perf.benchmark_return_5yr == Decimal('0.0850')
        assert perf.benchmark_return_10yr == Decimal('0.0950')

    def test_benchmark_broad_based_takes_priority(
        self, session, sample_etfs_with_class_id, mock_ncsr_db
    ):
        """BroadBasedIndexAxis data wins over AdditionalIndexAxis when both are present."""
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                # BroadBasedIndexAxis rows (ClassAxis is NULL)
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                # AdditionalIndexAxis rows (ClassAxis is NULL)
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
            ],
            'numeric_value': [
                Decimal('0.1200'),  # 1yr fund return
                Decimal('0.0800'),  # 5yr fund return
                Decimal('0.1100'),  # 1yr broad-based benchmark return
                Decimal('0.0750'),  # 5yr broad-based benchmark return
                Decimal('0.0600'),  # 1yr additional benchmark return (should be ignored)
                Decimal('0.0400'),  # 5yr additional benchmark return (should be ignored)
            ],
            'period_start': [
                date(2023, 10, 31),
                date(2019, 10, 31),
                date(2023, 10, 31),
                date(2019, 10, 31),
                date(2023, 10, 31),
                date(2019, 10, 31),
            ],
            'period_end': [
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
                date(2024, 10, 31),
            ],
            'dim_oef_ClassAxis': [
                'ist:C000131291Member',
                'ist:C000131291Member',
                None,
                None,
                None,
                None,
            ],
            'dim_oef_BroadBasedIndexAxis': [
                None,
                None,
                'ist:SP500IndexMember',   # Broad-based benchmark
                'ist:SP500IndexMember',
                None,
                None,
            ],
            'dim_oef_AdditionalIndexAxis': [
                None,
                None,
                None,
                None,
                'ist:NasdaqCompositeIndexMember',  # Additional benchmark (lower priority)
                'ist:NasdaqCompositeIndexMember',
            ],
        }
        mock_df = pd.DataFrame(data)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = mock_df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        stmt = select(Performance).where(
            Performance.etf_id == sample_etfs_with_class_id[0].id
        )
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        # benchmark_name and returns come from BroadBasedIndexAxis, not AdditionalIndexAxis
        assert perf.benchmark_name == "SP500IndexMember"
        assert perf.benchmark_return_1yr == Decimal('0.1100')
        assert perf.benchmark_return_5yr == Decimal('0.0750')
        # AdditionalIndexAxis values were NOT used
        assert perf.benchmark_name != "NasdaqCompositeIndexMember"
        assert perf.benchmark_return_1yr != Decimal('0.0600')

    def test_benchmark_null_does_not_overwrite(
        self, session, sample_etfs_with_class_id, mock_ncsr_db
    ):
        """A filing with no benchmark data does not overwrite existing benchmark values."""
        etf = sample_etfs_with_class_id[0]

        # Seed a Performance record with benchmark data already populated
        existing_perf = Performance(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 10, 31),
            filing_date=date(2024, 12, 1),
            return_1yr=Decimal('0.1234'),
            benchmark_name="SP500IndexMember",
            benchmark_return_1yr=Decimal('0.1100'),
            benchmark_return_5yr=Decimal('0.0800'),
            benchmark_return_10yr=Decimal('0.0880'),
            expense_ratio_actual=Decimal('0.0003'),
        )
        session.add(existing_perf)
        session.commit()

        # Now process a filing that has expense data but NO benchmark axis at all
        data = {
            'concept': [
                'oef:ExpenseRatioPct',
            ],
            'numeric_value': [
                Decimal('0.0002'),  # Updated expense ratio
            ],
            'period_start': [None],
            'period_end': [date(2024, 10, 31)],
            'dim_oef_ClassAxis': ['ist:C000131291Member'],
            'dim_oef_BroadBasedIndexAxis': [None],
        }
        mock_df = pd.DataFrame(data)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance

            mock_filing = Mock()
            mock_filing.filing_date = date(2024, 12, 1)
            mock_filing.is_inline_xbrl = True
            mock_xbrl = Mock()
            mock_facts = Mock()
            mock_facts.to_dataframe.return_value = mock_df
            mock_xbrl.facts = mock_facts
            mock_filing.xbrl.return_value = mock_xbrl

            mock_filings = Mock()
            mock_filings.__iter__ = Mock(return_value=iter([mock_filing]))
            mock_filings.__getitem__ = Mock(side_effect=lambda i: [mock_filing][i])
            mock_filings.__len__ = Mock(return_value=1)
            mock_filings.empty = False
            mock_instance.get_filings.return_value = mock_filings

            parse_ncsr(cik="0001100663", clear_cache=False)

        # Fetch the updated record
        session.expire_all()
        stmt = select(Performance).where(
            Performance.etf_id == etf.id
        )
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        # expense_ratio was updated by the new filing
        assert perf.expense_ratio_actual == Decimal('0.0002')
        # benchmark fields were NOT overwritten — original values preserved
        assert perf.benchmark_name == "SP500IndexMember"
        assert perf.benchmark_return_1yr == Decimal('0.1100')
        assert perf.benchmark_return_5yr == Decimal('0.0800')
        assert perf.benchmark_return_10yr == Decimal('0.0880')


class TestNCSRUITFallback:
    """Test N-CSR parser UIT fallback for ETFs with NULL class_id."""

    @pytest.fixture
    def uit_etf(self, session):
        """Create a single UIT ETF with NULL class_id."""
        etf = ETF(
            ticker="SPY",
            cik="0000884394",
            series_id=None,
            class_id=None,
            issuer_name="SPDR S&P 500 ETF Trust",
            fund_name="SPDR S&P 500 ETF Trust",
        )
        session.add(etf)
        session.commit()
        return etf

    @pytest.fixture
    def uit_etf_two_funds(self, session):
        """Create two UIT ETFs with NULL class_id under the same CIK (ambiguous case)."""
        etfs = [
            ETF(
                ticker="SPY",
                cik="0000884394",
                series_id=None,
                class_id=None,
                issuer_name="SPDR S&P 500 ETF Trust",
                fund_name="SPDR S&P 500 ETF Trust",
            ),
            ETF(
                ticker="SPY2",
                cik="0000884394",
                series_id=None,
                class_id=None,
                issuer_name="SPDR S&P 500 ETF Trust",
                fund_name="Another fund same CIK",
            ),
        ]
        for etf in etfs:
            session.add(etf)
        session.commit()
        return etfs

    def _make_mock_filing(self, df, filing_date=date(2024, 9, 30)):
        mock_filing = Mock()
        mock_filing.filing_date = filing_date
        mock_filing.is_inline_xbrl = True
        mock_xbrl = Mock()
        mock_facts = Mock()
        mock_facts.to_dataframe.return_value = df
        mock_xbrl.facts = mock_facts
        mock_filing.xbrl.return_value = mock_xbrl
        return mock_filing

    def _mock_filings(self, filings_list):
        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(side_effect=lambda i: filings_list[i])
        mock_filings.__len__ = Mock(return_value=len(filings_list))
        mock_filings.__bool__ = Mock(return_value=True)
        mock_filings.empty = False
        return mock_filings

    def test_uit_fallback_no_class_axis_column(self, session, uit_etf, mock_ncsr_db):
        """UIT filing with no ClassAxis column uses fallback ETF for all facts."""
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
                'oef:ExpenseRatioPct',
            ],
            'numeric_value': [
                Decimal('0.2650'),
                Decimal('0.1450'),
                Decimal('0.0009'),
            ],
            'period_start': [
                date(2023, 9, 30),
                date(2019, 9, 30),
                None,
            ],
            'period_end': [
                date(2024, 9, 30),
                date(2024, 9, 30),
                date(2024, 9, 30),
            ],
            # No dim_oef_ClassAxis column at all
        }
        mock_df = pd.DataFrame(data)
        mock_filing = self._make_mock_filing(mock_df)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            mock_instance.get_filings.return_value = self._mock_filings([mock_filing])

            parse_ncsr(cik="0000884394", clear_cache=False)

        stmt = select(Performance).where(Performance.etf_id == uit_etf.id)
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        assert perf.fiscal_year_end == date(2024, 9, 30)
        assert perf.return_1yr == Decimal('0.2650')
        assert perf.return_5yr == Decimal('0.1450')
        assert perf.expense_ratio_actual == Decimal('0.0009')

    def test_uit_fallback_all_null_class_axis(self, session, uit_etf, mock_ncsr_db):
        """UIT filing where ClassAxis column exists but all values are NULL."""
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:ExpenseRatioPct',
            ],
            'numeric_value': [
                Decimal('0.2650'),
                Decimal('0.0009'),
            ],
            'period_start': [
                date(2023, 9, 30),
                None,
            ],
            'period_end': [
                date(2024, 9, 30),
                date(2024, 9, 30),
            ],
            'dim_oef_ClassAxis': [None, None],
        }
        mock_df = pd.DataFrame(data)
        mock_filing = self._make_mock_filing(mock_df)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            mock_instance.get_filings.return_value = self._mock_filings([mock_filing])

            parse_ncsr(cik="0000884394", clear_cache=False)

        stmt = select(Performance).where(Performance.etf_id == uit_etf.id)
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        assert perf.return_1yr == Decimal('0.2650')
        assert perf.expense_ratio_actual == Decimal('0.0009')

    def test_uit_fallback_with_benchmark(self, session, uit_etf, mock_ncsr_db):
        """UIT filing with no ClassAxis extracts benchmark data correctly."""
        data = {
            'concept': [
                'oef:AvgAnnlRtrPct',
                'oef:AvgAnnlRtrPct',
            ],
            'numeric_value': [
                Decimal('0.2650'),
                Decimal('0.2600'),
            ],
            'period_start': [
                date(2023, 9, 30),
                date(2023, 9, 30),
            ],
            'period_end': [
                date(2024, 9, 30),
                date(2024, 9, 30),
            ],
            'dim_oef_BroadBasedIndexAxis': [
                None,
                'ist:SP500TotalReturnIndexMember',
            ],
            # No dim_oef_ClassAxis column
        }
        mock_df = pd.DataFrame(data)
        mock_filing = self._make_mock_filing(mock_df)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            mock_instance.get_filings.return_value = self._mock_filings([mock_filing])

            parse_ncsr(cik="0000884394", clear_cache=False)

        stmt = select(Performance).where(Performance.etf_id == uit_etf.id)
        perf = session.execute(stmt).scalar_one_or_none()

        assert perf is not None
        assert perf.return_1yr == Decimal('0.2650')
        assert perf.benchmark_name == "SP500TotalReturnIndexMember"
        assert perf.benchmark_return_1yr == Decimal('0.2600')

    def test_uit_ambiguous_multiple_null_class_id(self, session, uit_etf_two_funds, mock_ncsr_db):
        """Multiple ETFs with NULL class_id under same CIK are skipped as ambiguous."""
        data = {
            'concept': ['oef:AvgAnnlRtrPct'],
            'numeric_value': [Decimal('0.2650')],
            'period_start': [date(2023, 9, 30)],
            'period_end': [date(2024, 9, 30)],
        }
        mock_df = pd.DataFrame(data)
        mock_filing = self._make_mock_filing(mock_df)

        with patch("etf_pipeline.parsers.ncsr.Company") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            mock_instance.get_filings.return_value = self._mock_filings([mock_filing])

            parse_ncsr(cik="0000884394", clear_cache=False)

        stmt = select(Performance)
        results = session.execute(stmt).scalars().all()
        assert len(results) == 0
