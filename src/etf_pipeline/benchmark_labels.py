"""Benchmark label resolution from XBRL extension taxonomies."""

import logging
import re
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from etf_pipeline.models import BenchmarkMapping
from etf_pipeline.parser_utils import upsert_benchmark_mapping

logger = logging.getLogger(__name__)

SOURCE_TAXONOMY = "taxonomy_label"
SOURCE_HEURISTIC = "heuristic"
SOURCE_HTML = "filing_html"
SOURCE_MANUAL = "manual"

# Substitutions applied in order before CamelCase splitting.
# Each entry is (pattern, replacement) passed to re.sub.
_ABBREV_SUBS = [
    # SP500 must come before SP so it isn't partially replaced
    (r'SP500', 'S&P 500'),
    # SP followed by an uppercase letter that has more characters after it -> S&P
    # Requires at least 2 chars after SP to avoid false positives on tickers like SPY.
    # Negative lookbehind prevents matching mid-word (e.g. "ESPN").
    (r'(?<![A-Za-z])SP(?=[A-Z][A-Za-z])', 'S&P '),
]

# Suffixes to strip from raw member IDs before processing (case-sensitive, longest first).
_STRIP_SUFFIXES = [
    'BroadBasedIndexMember',
    'AdditionalIndexMember',
    'IndexMember',
    'Member',
]


def _heuristic_label(member_id: str) -> Optional[str]:
    """Attempt to produce a human-readable label from a raw XBRL member ID.

    Steps:
    1. Strip known trailing suffixes (e.g. 'Member', 'BroadBasedIndexMember').
    2. Insert spaces before capital letters (CamelCase -> words).
    3. Apply known abbreviation fixups (e.g. 'SP500' -> 'S&P 500').
    4. Collapse whitespace and strip.

    Returns None if the result is an empty string or looks like it was not
    meaningfully transformed (fewer than 3 characters).
    """
    if not member_id:
        return None

    text = member_id

    # Strip known suffixes
    for suffix in _STRIP_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break

    if not text:
        return None

    # Apply abbreviation subs before splitting (they may contain digits/symbols)
    for pattern, replacement in _ABBREV_SUBS:
        text = re.sub(pattern, replacement, text)

    # Insert a space before each capital letter that follows a lowercase letter or digit
    # e.g. "BloombergUSAggregate" -> "Bloomberg U S Aggregate"
    text = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', text)
    # Also split before a capital followed by lowercase when preceded by consecutive caps
    # e.g. "USAggregate" -> "US Aggregate"
    text = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', text)

    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) < 3:
        return None

    return text

TERSE_LABEL_ROLE = "http://www.xbrl.org/2003/role/terseLabel"
STANDARD_LABEL_ROLE = "http://www.xbrl.org/2003/role/label"


def _extract_label_from_xbrl(xbrl_obj, member_id: str) -> Optional[str]:
    """Extract human-readable label for a member from XBRL element catalog.

    The member_id stored in the DB is the namespace-stripped version (e.g.,
    'BloombergUSAggregateBondIndexMember'). The element_catalog keys include
    namespace prefixes (e.g., 'ist_BloombergUSAggregateBondIndexMember').

    We need to search for the member_id as a suffix match in the catalog.
    """
    if not xbrl_obj or not hasattr(xbrl_obj, 'element_catalog'):
        return None

    catalog = xbrl_obj.element_catalog

    if not isinstance(catalog, dict):
        return None

    # Try direct lookup first
    if member_id in catalog:
        return _get_best_label(catalog[member_id])

    bare_to_key = {}
    for k in catalog:
        bare = k.split('_', 1)[-1] if '_' in k else k.split(':', 1)[-1] if ':' in k else k
        bare_to_key.setdefault(bare, k)
    key = bare_to_key.get(member_id)
    if key is not None:
        return _get_best_label(catalog[key])

    return None


def _get_best_label(element) -> Optional[str]:
    """Get the best human-readable label from an XBRL element.

    Prefers terseLabel (cleaner), falls back to standard label.
    Strips '[Member]' suffix if present.
    """
    if not hasattr(element, 'labels'):
        return None

    labels = element.labels

    # Prefer terse label (cleaner, no "[Member]" suffix typically)
    label = labels.get(TERSE_LABEL_ROLE)
    if label:
        return _clean_label(label)

    # Fall back to standard label
    label = labels.get(STANDARD_LABEL_ROLE)
    if label:
        return _clean_label(label)

    return None


def _clean_label(label: str) -> str:
    """Clean up a label string."""
    if label.endswith('[Member]'):
        label = label[:-8].strip()
    return label.strip()


def resolve_benchmark_label(
    session: Session,
    member_id: str,
    xbrl_obj=None,
    cik: Optional[str] = None,
    filing_date: Optional[date] = None,
) -> Optional[str]:
    """Resolve a benchmark member_id to a human-readable label.

    Checks the DB cache first. On cache miss, extracts from XBRL
    and upserts to the mapping table.

    Args:
        session: SQLAlchemy session
        member_id: Raw XBRL member ID (e.g., 'BloombergUSAggregateBondIndexMember')
        xbrl_obj: XBRL object from edgartools (filing.xbrl())
        cik: CIK of the filing (for provenance tracking)
        filing_date: Date of the filing

    Returns:
        Human-readable label or None if not resolvable
    """
    if not member_id:
        return None

    # Check DB cache
    existing = session.query(BenchmarkMapping).filter_by(member_id=member_id).first()
    if existing and existing.readable_name:
        return existing.readable_name

    # Try to extract from XBRL
    label = _extract_label_from_xbrl(xbrl_obj, member_id)

    if label:
        upsert_benchmark_mapping(session, member_id, label, SOURCE_TAXONOMY, cik=cik, filing_date=filing_date)
        try:
            session.flush()
        except Exception:
            session.rollback()
            logger.warning("Failed to upsert benchmark mapping for %s", member_id)

        return label

    # Record the member_id even if we couldn't resolve it (prevents re-lookup)
    if not existing:
        mapping = BenchmarkMapping(
            member_id=member_id,
            readable_name=None,
            source=None,
            first_seen_cik=cik,
            first_seen_date=filing_date,
        )
        session.add(mapping)
        try:
            session.flush()
        except Exception:
            session.rollback()
            logger.warning("Failed to record unresolved benchmark mapping for %s", member_id)

    return None
