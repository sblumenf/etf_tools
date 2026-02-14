"""Parse 485BPOS (prospectus) filings for fee/expense data using iXBRL.

This parser extracts data from the Risk/Return Summary section of prospectuses,
which uses the RR (Risk/Return) XBRL taxonomy. Data is embedded in HTML using
inline XBRL (iXBRL) tags.
"""

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 547  # 18-month window for prospectus filings


def parse_contexts(soup: BeautifulSoup) -> dict[str, dict[str, Optional[str]]]:
    """Extract context map: context_id → {cik, series_id, class_id}.

    Contexts are defined in <xbrli:context> elements within <ix:resources>.
    Each context has a unique id and may contain:
    - CIK (from xbrli:identifier)
    - Series ID (from dei:LegalEntityAxis member, format: S000014796Member)
    - Class ID (from rr:ProspectusShareClassAxis member, format: C000014542Member)

    Args:
        soup: BeautifulSoup object of the iXBRL filing

    Returns:
        Dict mapping context_id to {cik, series_id, class_id}

    Example:
        {
            "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member": {
                "cik": "0001314612",
                "series_id": "S000014796",
                "class_id": "C000014542"
            }
        }
    """
    context_map = {}

    # Find all context elements (namespace-aware: xbrli:context)
    contexts = soup.find_all('xbrli:context')

    for context in contexts:
        context_id = context.get('id')
        if not context_id:
            continue

        # Extract CIK from xbrli:identifier
        cik = None
        identifier = context.find('xbrli:identifier')
        if identifier:
            cik_text = identifier.get_text().strip()
            # Normalize to 10 digits
            if cik_text:
                try:
                    cik = f"{int(cik_text):010d}"
                except ValueError:
                    logger.warning(f"Invalid CIK format: {cik_text}")

        # Extract series_id and class_id from segment dimensions
        series_id = None
        class_id = None

        segment = context.find('xbrli:segment')
        if segment:
            members = segment.find_all('xbrldi:explicitmember')
            for member in members:
                dimension = member.get('dimension', '')
                member_value = member.get_text().strip()

                # Extract series_id from LegalEntityAxis
                if 'legalentityaxis' in dimension.lower():
                    # Format: "rr01:S000014796Member" or "S000014796Member"
                    match = re.search(r'(S\d+)Member', member_value, re.IGNORECASE)
                    if match:
                        series_id = match.group(1).upper()

                # Extract class_id from ProspectusShareClassAxis (RR) or ClassAxis (OEF)
                elif 'prospectusshare' in dimension.lower() or 'classaxis' in dimension.lower():
                    # Format: "rr01:C000014542Member" or "C000014542Member"
                    match = re.search(r'(C\d+)Member', member_value, re.IGNORECASE)
                    if match:
                        class_id = match.group(1).upper()

        context_map[context_id] = {
            'cik': cik,
            'series_id': series_id,
            'class_id': class_id,
        }

    return context_map


def convert_numeric_value(
    element,
    scale: Optional[str] = None,
    format_attr: Optional[str] = None,
    sign: Optional[str] = None,
    negate_to_positive: bool = False,
) -> Optional[Decimal]:
    """Apply scale, format, and type conversions to numeric iXBRL element.

    Conversion rules:
    1. Scale factor -2: displayed 0.70 → Decimal('0.0070')
       Formula: value * 10^scale = 0.70 * 10^-2 = 0.007
    2. Format "ixt-sec:numwordsen" with text "None" → NULL
    3. Format "ixt:zerodash" with text "—" → Decimal('0')
    4. Sign "-": negate the value
    5. negate_to_positive=True: if value is negative, convert to positive

    Args:
        element: BeautifulSoup element (ix:nonFraction)
        scale: Scale attribute value (e.g., "-2")
        format_attr: Format attribute value (e.g., "ixt:numdotdecimal")
        sign: Sign attribute value (e.g., "-")
        negate_to_positive: If True, negate negative values to positive

    Returns:
        Decimal value or None
    """
    if element is None:
        return None

    text = element.get_text().strip()

    # Handle format transformations
    if format_attr:
        # ixt-sec:numwordsen "None" → NULL
        if 'numwordsen' in format_attr.lower():
            if text.lower() in ('none', 'n/a'):
                return None

        # ixt:zerodash "—" → Decimal('0')
        if 'zerodash' in format_attr.lower():
            if text in ('—', '-', '–', ''):
                return Decimal('0')

    # Parse numeric value
    # Remove common formatting: commas, percent signs, dollar signs
    clean_text = text.replace(',', '').replace('$', '').replace('%', '')

    if not clean_text or clean_text in ('—', '-', '–'):
        return None

    try:
        value = Decimal(clean_text)
    except (ValueError, InvalidOperation):
        logger.warning(f"Failed to parse numeric value: '{text}'")
        return None

    # Apply sign attribute
    if sign == '-':
        value = -value

    # Apply scale factor
    # Scale -2 means: displayed_value * 10^-2 = actual_value
    # Example: 0.70 with scale=-2 → 0.70 * 0.01 = 0.007
    if scale:
        try:
            scale_int = int(scale)
            value = value * (Decimal('10') ** scale_int)
        except ValueError:
            logger.warning(f"Invalid scale value: {scale}")

    # Optionally negate negative values to positive
    # (used for fee waivers and redemption fees which may be reported as negative)
    if negate_to_positive and value < 0:
        value = -value

    return value


def strip_html_to_text(html_fragment: str) -> str:
    """Strip HTML tags and return plain text.

    Args:
        html_fragment: HTML string (may contain <p>, <b>, <i>, etc.)

    Returns:
        Plain text with HTML tags removed
    """
    if not html_fragment:
        return ''

    soup = BeautifulSoup(html_fragment, 'html.parser')
    text = soup.get_text()

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def build_tag_index(soup: BeautifulSoup) -> dict[tuple[str, str], Any]:
    """Build an index of all iXBRL tags keyed by (tag_name, context_id).

    This pre-indexes all ix:nonfraction and ix:nonnumeric elements to enable
    O(1) lookups instead of O(n) scans for each field extraction.

    Args:
        soup: BeautifulSoup object of the filing

    Returns:
        Dict mapping (tag_name, context_id) to BeautifulSoup element
    """
    tag_index = {}

    # Find all iXBRL tags once
    for element in soup.find_all(['ix:nonfraction', 'ix:nonnumeric']):
        tag_name = element.get('name')
        context_id = element.get('contextref')

        if tag_name and context_id:
            # Use first occurrence if multiple tags with same (name, contextref)
            key = (tag_name, context_id)
            if key not in tag_index:
                tag_index[key] = element

    return tag_index


def extract_tag_value(
    soup_or_index,
    tag_name: str,
    context_id: str,
    negate_to_positive: bool = False,
) -> Optional[Decimal | str]:
    """Extract and convert value for a given RR tag and context.

    Args:
        soup_or_index: BeautifulSoup object OR tag index dict (for performance)
        tag_name: Full tag name (e.g., "rr:ManagementFeesOverAssets")
        context_id: Context ID to match
        negate_to_positive: If True, negate negative numeric values to positive

    Returns:
        Decimal for numeric tags, str for text tags, or None if not found
    """
    # Support both BeautifulSoup (legacy) and dict index (optimized)
    if isinstance(soup_or_index, dict):
        # O(1) lookup from pre-built index
        element = soup_or_index.get((tag_name, context_id))
        if not element:
            return None
    else:
        # O(n) scan for backward compatibility
        soup = soup_or_index
        elements = soup.find_all(
            lambda tag: tag.name in ('ix:nonfraction', 'ix:nonnumeric')
            and tag.get('name') == tag_name
            and tag.get('contextref') == context_id
        )

        if not elements:
            return None

        # Use the first matching element
        element = elements[0]

    # Handle numeric tags (ix:nonFraction)
    if element.name == 'ix:nonfraction':
        scale = element.get('scale')
        format_attr = element.get('format')
        sign = element.get('sign')

        return convert_numeric_value(
            element,
            scale=scale,
            format_attr=format_attr,
            sign=sign,
            negate_to_positive=negate_to_positive,
        )

    # Handle text tags (ix:nonNumeric)
    elif element.name == 'ix:nonnumeric':
        # Check if it's a text block (contains HTML)
        escape_attr = element.get('escape')
        if escape_attr == 'true':
            # Extract inner HTML and strip tags
            inner_html = element.decode_contents()
            return strip_html_to_text(inner_html)
        else:
            # Simple text value
            return element.get_text().strip()

    return None


def parse_date_tag(
    soup_or_index,
    tag_name: str,
    context_id: str,
) -> Optional[date]:
    """Extract and parse a date from an iXBRL tag.

    Args:
        soup_or_index: BeautifulSoup object OR tag index dict (for performance)
        tag_name: Full tag name (e.g., "dei:DocumentPeriodEndDate")
        context_id: Context ID to match

    Returns:
        date object or None
    """
    value = extract_tag_value(soup_or_index, tag_name, context_id)
    if not value or not isinstance(value, str):
        return None

    # Try parsing various date formats
    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y']:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    logger.warning(f"Failed to parse date: '{value}'")
    return None



def _process_cik_prospectus(session, cik: str) -> bool:
    """Process 485BPOS filing for a single CIK.

    Extracts fee schedules, shareholder fees, expense examples, and narrative text
    from the most recent 485BPOS filing for this CIK.

    Args:
        session: SQLAlchemy session
        cik: CIK string (zero-padded to 10 digits)

    Returns:
        True if successful, False otherwise
    """
    from edgar import Company
    from etf_pipeline.models import ETF, FeeExpense, ShareholderFee, ExpenseExample
    from etf_pipeline.parser_utils import ensure_date, update_processing_log
    from sqlalchemy import select

    try:
        # Build class_id -> ETF and series_id -> list[ETF] mappings from database
        stmt = select(ETF).where(ETF.cik == cik)
        etfs = session.execute(stmt).scalars().all()

        class_id_to_etf = {}
        series_id_to_etfs = {}  # Map series_id to list of ETFs (multiple classes can share one series)
        for etf in etfs:
            if etf.class_id:
                class_id_to_etf[etf.class_id] = etf
            if etf.series_id:
                if etf.series_id not in series_id_to_etfs:
                    series_id_to_etfs[etf.series_id] = []
                series_id_to_etfs[etf.series_id].append(etf)

        if not class_id_to_etf:
            logger.warning(f"CIK {cik}: No ETFs with class_id found in database")
            return True

        needed_class_ids = set(class_id_to_etf.keys())
        satisfied = set()
        latest_filing_date = None

        # Fetch 485BPOS filings
        company = Company(cik)
        filings = company.get_filings(form='485BPOS')

        if not filings or (hasattr(filings, 'empty') and filings.empty):
            logger.info(f"CIK {cik}: No 485BPOS filings found")
            return True  # Not an error, just no data

        # Get most recent filing date and filter to 18-month window
        most_recent_filing = filings[0]
        most_recent_date = most_recent_filing.filing_date if hasattr(most_recent_filing, 'filing_date') else date.today()

        # Calculate cutoff date
        cutoff_date = most_recent_date - timedelta(days=LOOKBACK_DAYS)

        # Iterate through filings in reverse chronological order
        for filing_idx in range(len(filings)):
            # Stop if all class_ids satisfied
            if not (needed_class_ids - satisfied):
                logger.debug(f"CIK {cik}: All class_ids satisfied after {filing_idx} filing(s)")
                break

            filing = filings[filing_idx]
            filing_date = ensure_date(filing.filing_date)

            # Track the latest filing date
            if latest_filing_date is None or filing_date > latest_filing_date:
                latest_filing_date = filing_date

            # Stop if filing is outside 18-month window
            if filing_date < cutoff_date:
                logger.debug(f"CIK {cik}: Filing {filing_idx} outside 18-month window, stopping")
                break

            filing_url = filing.document.url if hasattr(filing, 'document') else None

            # Get HTML content
            html = filing.html()
            if not html:
                logger.warning(f"CIK {cik}: Filing {filing_idx} failed to fetch HTML content, skipping")
                continue

            # Parse iXBRL
            soup = BeautifulSoup(html, 'html.parser')

            # Extract contexts
            context_map = parse_contexts(soup)

            # Detect which namespace prefix is in use (rr: or oef:)
            rr_tags = soup.find_all(lambda tag: tag.get('name', '').startswith('rr:'))
            oef_tags = soup.find_all(lambda tag: tag.get('name', '').startswith('oef:'))

            if rr_tags:
                tag_prefix = 'rr'
            elif oef_tags:
                tag_prefix = 'oef'
            else:
                logger.warning(f"CIK {cik}: Filing {filing_idx} has no RR or OEF iXBRL tags, skipping")
                continue

            # Build tag index for O(1) lookups (performance optimization)
            tag_index = build_tag_index(soup)

            # Find the base context (no dimensions) for effective_date
            base_context_id = None
            for ctx_id, ctx_data in context_map.items():
                if ctx_data['series_id'] is None and ctx_data['class_id'] is None:
                    base_context_id = ctx_id
                    break

            # If no base context, try to find one with just CIK
            if not base_context_id and context_map:
                base_context_id = list(context_map.keys())[0]

            # Extract effective_date from DocumentPeriodEndDate
            effective_date = None
            if base_context_id:
                effective_date = parse_date_tag(tag_index, 'dei:DocumentPeriodEndDate', base_context_id)

            if not effective_date:
                logger.warning(f"CIK {cik}: Filing {filing_idx} has no effective_date, using filing date")
                effective_date = filing_date

            # Track which ETFs had data extracted in this filing
            etfs_with_data_this_filing = set()

            # Process each context that has a class_id
            for context_id, context_data in context_map.items():
                class_id = context_data.get('class_id')
                if not class_id:
                    continue

                # Skip if already satisfied
                if class_id in satisfied:
                    logger.debug(f"CIK {cik}: class_id {class_id} already satisfied, skipping")
                    continue

                # Match class_id to ETF
                etf = class_id_to_etf.get(class_id)
                if not etf:
                    logger.debug(f"CIK {cik}: class_id {class_id} not found in database, skipping")
                    continue

                # Extract fee data
                fee_data = {
                    'etf_id': etf.id,
                    'effective_date': effective_date,
                    'filing_date': filing_date,
                    'management_fee': extract_tag_value(tag_index, f'{tag_prefix}:ManagementFeesOverAssets', context_id),
                    'distribution_12b1': extract_tag_value(tag_index, f'{tag_prefix}:DistributionAndService12b1FeesOverAssets', context_id),
                    'other_expenses': extract_tag_value(tag_index, f'{tag_prefix}:OtherExpensesOverAssets', context_id),
                    'total_expense_gross': extract_tag_value(tag_index, f'{tag_prefix}:ExpensesOverAssets', context_id),
                    'fee_waiver': extract_tag_value(tag_index, f'{tag_prefix}:FeeWaiverOrReimbursementOverAssets', context_id, negate_to_positive=True),
                    'total_expense_net': extract_tag_value(tag_index, f'{tag_prefix}:NetExpensesOverAssets', context_id),
                    'acquired_fund_fees': extract_tag_value(tag_index, f'{tag_prefix}:AcquiredFundFeesAndExpensesOverAssets', context_id),
                }

                # Upsert FeeExpense (if any data present)
                if any(fee_data[k] is not None for k in fee_data if k not in ('etf_id', 'effective_date', 'filing_date')):
                    stmt = select(FeeExpense).where(
                        FeeExpense.etf_id == etf.id,
                        FeeExpense.effective_date == effective_date,
                        FeeExpense.filing_date == filing_date
                    )
                    existing = session.execute(stmt).scalar_one_or_none()

                    if existing:
                        # Update existing record
                        for field, value in fee_data.items():
                            if field not in ('etf_id', 'effective_date', 'filing_date') and value is not None:
                                setattr(existing, field, value)
                        logger.debug(f"CIK {cik}: Updated fee data for {etf.ticker}")
                    else:
                        # Insert new record
                        new_fee = FeeExpense(**fee_data)
                        session.add(new_fee)
                        logger.debug(f"CIK {cik}: Inserted fee data for {etf.ticker}")

                    etfs_with_data_this_filing.add(etf.id)

                # Extract shareholder fees
                shareholder_fee_data = {
                    'etf_id': etf.id,
                    'effective_date': effective_date,
                    'filing_date': filing_date,
                    'front_load': extract_tag_value(tag_index, f'{tag_prefix}:MaximumSalesChargeImposedOnPurchasesOverOfferingPrice', context_id),
                    'deferred_load': extract_tag_value(tag_index, f'{tag_prefix}:MaximumDeferredSalesChargeOverOther', context_id),
                    'reinvestment_charge': extract_tag_value(tag_index, f'{tag_prefix}:MaximumSalesChargeOnReinvestedDividendsAndDistributionsOverOther', context_id),
                    'redemption_fee': extract_tag_value(tag_index, f'{tag_prefix}:RedemptionFeeOverRedemption', context_id, negate_to_positive=True),
                    'exchange_fee': extract_tag_value(tag_index, f'{tag_prefix}:ExchangeFeeOverRedemption', context_id),
                }

                # Upsert ShareholderFee (if any data present)
                if any(shareholder_fee_data[k] is not None for k in shareholder_fee_data if k not in ('etf_id', 'effective_date', 'filing_date')):
                    stmt = select(ShareholderFee).where(
                        ShareholderFee.etf_id == etf.id,
                        ShareholderFee.effective_date == effective_date,
                        ShareholderFee.filing_date == filing_date
                    )
                    existing = session.execute(stmt).scalar_one_or_none()

                    if existing:
                        # Update existing record
                        for field, value in shareholder_fee_data.items():
                            if field not in ('etf_id', 'effective_date', 'filing_date') and value is not None:
                                setattr(existing, field, value)
                        logger.debug(f"CIK {cik}: Updated shareholder fees for {etf.ticker}")
                    else:
                        # Insert new record
                        new_shareholder_fee = ShareholderFee(**shareholder_fee_data)
                        session.add(new_shareholder_fee)
                        logger.debug(f"CIK {cik}: Inserted shareholder fees for {etf.ticker}")

                # Extract expense examples
                expense_example_data = {
                    'etf_id': etf.id,
                    'effective_date': effective_date,
                    'filing_date': filing_date,
                    'year_01': extract_tag_value(tag_index, f'{tag_prefix}:ExpenseExampleYear01', context_id),
                    'year_03': extract_tag_value(tag_index, f'{tag_prefix}:ExpenseExampleYear03', context_id),
                    'year_05': extract_tag_value(tag_index, f'{tag_prefix}:ExpenseExampleYear05', context_id),
                    'year_10': extract_tag_value(tag_index, f'{tag_prefix}:ExpenseExampleYear10', context_id),
                }

                # Convert Decimal to int for expense examples (they're dollar amounts)
                for key in ['year_01', 'year_03', 'year_05', 'year_10']:
                    if expense_example_data[key] is not None:
                        expense_example_data[key] = int(expense_example_data[key])

                # Upsert ExpenseExample (if any data present)
                if any(expense_example_data[k] is not None for k in expense_example_data if k not in ('etf_id', 'effective_date', 'filing_date')):
                    stmt = select(ExpenseExample).where(
                        ExpenseExample.etf_id == etf.id,
                        ExpenseExample.effective_date == effective_date,
                        ExpenseExample.filing_date == filing_date
                    )
                    existing = session.execute(stmt).scalar_one_or_none()

                    if existing:
                        # Update existing record
                        for field, value in expense_example_data.items():
                            if field not in ('etf_id', 'effective_date', 'filing_date') and value is not None:
                                setattr(existing, field, value)
                        logger.debug(f"CIK {cik}: Updated expense examples for {etf.ticker}")
                    else:
                        # Insert new record
                        new_expense_example = ExpenseExample(**expense_example_data)
                        session.add(new_expense_example)
                        logger.debug(f"CIK {cik}: Inserted expense examples for {etf.ticker}")

                # Mark this class_id as satisfied
                satisfied.add(class_id)

            # Extract narrative text (series-level, not class-level)
            for context_id, context_data in context_map.items():
                series_id = context_data.get('series_id')
                class_id = context_data.get('class_id')

                # Series-level context (no class dimension)
                if series_id and not class_id:
                    etf_list = series_id_to_etfs.get(series_id)
                    if not etf_list:
                        logger.debug(f"CIK {cik}: series_id {series_id} not found in database, skipping narrative text")
                        continue

                    # Extract objective and strategy text
                    objective_text = extract_tag_value(tag_index, f'{tag_prefix}:ObjectivePrimaryTextBlock', context_id)
                    strategy_text = extract_tag_value(tag_index, f'{tag_prefix}:StrategyNarrativeTextBlock', context_id)

                    # Update all ETFs with this series_id (multiple share classes can belong to same series)
                    for etf in etf_list:
                        if objective_text:
                            etf.objective_text = objective_text
                            logger.debug(f"CIK {cik}: Updated objective_text for {etf.ticker}")

                        if strategy_text:
                            etf.strategy_text = strategy_text
                            logger.debug(f"CIK {cik}: Updated strategy_text for {etf.ticker}")

            # Update filing_url for ETFs processed in this filing
            if filing_url:
                for etf_id in etfs_with_data_this_filing:
                    etf = session.get(ETF, etf_id)
                    if etf:
                        etf.filing_url = filing_url
                        logger.debug(f"CIK {cik}: Updated filing_url for {etf.ticker}")

        # Update processing log after successful processing
        if latest_filing_date is not None:
            latest_filing_date = ensure_date(latest_filing_date)
            update_processing_log(session, cik, "prospectus", latest_filing_date)

        session.commit()
        logger.info(f"CIK {cik}: Successfully processed 485BPOS filing")
        return True

    except Exception as e:
        logger.error(f"CIK {cik}: Error processing 485BPOS filing: {e}")
        session.rollback()
        return False


def parse_prospectus(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None:
    """Parse 485BPOS filings for fee schedules and strategy.

    Args:
        cik: Optional CIK to process (all others will be skipped)
        ciks: Optional list of CIKs to process (overrides cik param)
        limit: Optional limit on number of CIKs to process
        clear_cache: Whether to clear edgartools HTTP cache after processing
    """
    from edgar import clear_cache as edgar_clear_cache
    from etf_pipeline.db import get_engine
    from etf_pipeline.models import ETF
    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    # Determine which CIKs to process
    with session_factory() as session:
        if ciks is not None:
            # List of CIKs provided
            cik_list = [f"{int(c):010d}" for c in ciks]
            logger.info(f"Processing {len(cik_list)} CIK(s) from ciks parameter")
        elif cik is not None:
            # Single CIK provided
            cik_padded = f"{int(cik):010d}"
            cik_list = [cik_padded]
            logger.info(f"Processing single CIK: {cik_padded}")
        else:
            # Get all distinct CIKs from ETF table
            stmt = select(ETF.cik).distinct().order_by(ETF.cik)
            cik_list = [row[0] for row in session.execute(stmt).all()]

            if not cik_list:
                logger.warning("No CIKs found in ETF table. Run 'load-etfs' first.")
                print("No CIKs found in ETF table. Run 'load-etfs' first.")
                return

        if limit is not None and ciks is None:
            cik_list = cik_list[:limit]
            logger.info(f"Limiting to first {limit} CIKs")

    succeeded = 0
    failed = 0

    for cik_str in cik_list:
        with session_factory() as session:
            if _process_cik_prospectus(session, cik_str):
                succeeded += 1
            else:
                failed += 1

    print(f"\nSummary: {succeeded} CIKs succeeded, {failed} CIKs failed")
    logger.info(f"Summary: {succeeded} CIKs succeeded, {failed} CIKs failed")

    if clear_cache:
        result = edgar_clear_cache(dry_run=False)
        files_deleted = result.get('files_deleted', 0)
        bytes_freed = result.get('bytes_freed', 0)
        mb_freed = bytes_freed / (1024 * 1024)
        logger.info(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")
        print(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")
