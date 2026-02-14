"""SGML header parsing utilities for SEC EDGAR filings."""

import re


def parse_series_class_info(header_text: str) -> dict:
    """Parse SGML header for series and class/contract information.

    Args:
        header_text: SGML header text from filing.header.text

    Returns:
        Dictionary with:
            'series': {series_id: series_name, ...}
            'classes': {(series_name_lower, class_name_lower): class_id, ...}
            'tickers': {ticker: class_id, ...}
    """
    result = {
        'series': {},
        'classes': {},
        'tickers': {}
    }

    if not header_text:
        return result

    series_blocks = re.findall(r'<SERIES>(.*?)</SERIES>', header_text, re.DOTALL)

    for series_block in series_blocks:
        series_name_match = re.search(r'<SERIES-NAME>(.*?)(?:\n|<)', series_block)
        if not series_name_match:
            continue

        series_name = series_name_match.group(1).strip()
        normalized_series = series_name.lower()

        series_id_match = re.search(r'<SERIES-ID>(.*?)(?:\n|<)', series_block)
        if series_id_match:
            series_id = series_id_match.group(1).strip()
            if series_id and series_name:
                result['series'][series_id] = series_name

        class_blocks = re.findall(r'<CLASS-CONTRACT>(.*?)</CLASS-CONTRACT>', series_block, re.DOTALL)

        for class_block in class_blocks:
            class_id_match = re.search(r'<CLASS-CONTRACT-ID>(.*?)(?:\n|<)', class_block)
            if not class_id_match:
                continue

            class_id = class_id_match.group(1).strip()

            class_name_match = re.search(r'<CLASS-CONTRACT-NAME>(.*?)(?:\n|<)', class_block)
            if class_name_match:
                class_name = class_name_match.group(1).strip()
                normalized_class = class_name.lower()
                result['classes'][(normalized_series, normalized_class)] = class_id

            ticker_match = re.search(r'<CLASS-CONTRACT-TICKER-SYMBOL>(.*?)(?:\n|<)', class_block)
            if ticker_match:
                ticker = ticker_match.group(1).strip()
                if ticker:
                    result['tickers'][ticker] = class_id

    return result
