"""Benchmark label resolution from XBRL extension taxonomies."""

import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from etf_pipeline.models import BenchmarkMapping

logger = logging.getLogger(__name__)

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

    # Try with common namespace prefixes (suffix match)
    for key in catalog:
        # Match on the part after the namespace prefix (after underscore or colon)
        bare_key = key.split('_', 1)[-1] if '_' in key else key.split(':', 1)[-1] if ':' in key else key
        if bare_key == member_id:
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
        # Upsert to mapping table
        if existing:
            existing.readable_name = label
            existing.source = "taxonomy_label"
        else:
            mapping = BenchmarkMapping(
                member_id=member_id,
                readable_name=label,
                source="taxonomy_label",
                first_seen_cik=cik,
                first_seen_date=filing_date,
            )
            session.add(mapping)

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

    return None
