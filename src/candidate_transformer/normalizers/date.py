"""Date normalizer → ``YYYY-MM`` format.

Accepted inputs:
- ``MM/YYYY`` → ``YYYY-MM``
- ``Month YYYY`` (e.g. "March 2020") → ``2020-03``
- ``YYYY`` (year only) → ``YYYY-01`` with method tag ``year_only_approximated``
- ISO dates (``2020-03-15``, ``2020-03``) → ``YYYY-MM``
- ``"Present"`` / ``"Current"`` / ``null`` → ``None`` (indicates ongoing)

Returns a tuple of ``(normalized_date_str | None, method_tag)`` so the caller
can annotate provenance with the method used.
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_MONTH_NAMES: dict[str, str] = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}

# Patterns, tried in order.
_RE_ISO_FULL = re.compile(r"^(\d{4})-(\d{1,2})-\d{1,2}$")       # 2020-03-15
_RE_ISO_MONTH = re.compile(r"^(\d{4})-(\d{1,2})$")               # 2020-03
_RE_SLASH = re.compile(r"^(\d{1,2})/(\d{4})$")                   # 03/2020
_RE_MONTH_YEAR = re.compile(r"^([A-Za-z]+)\s+(\d{4})$")          # March 2020
_RE_YEAR_ONLY = re.compile(r"^(\d{4})$")                         # 2020


def normalize_date(raw: str | None) -> tuple[str | None, str]:
    """Normalise *raw* date string to ``YYYY-MM``.

    Returns:
        ``(normalised_string, method_tag)`` — method_tag is one of:
        - ``"exact"`` — full date parsed without loss
        - ``"year_only_approximated"`` — year-only input, month set to 01
        - ``"present"`` — ongoing / current position (value is None)
        - ``"unparseable"`` — could not parse (value is None)
    """
    if raw is None:
        return None, "present"

    text = raw.strip()
    if not text:
        return None, "present"

    # "Present" / "Current" → ongoing.
    if text.lower() in {"present", "current", "now", "ongoing"}:
        return None, "present"

    # ISO full date: 2020-03-15
    m = _RE_ISO_FULL.match(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}", "exact"

    # ISO month: 2020-03
    m = _RE_ISO_MONTH.match(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}", "exact"

    # MM/YYYY
    m = _RE_SLASH.match(text)
    if m:
        month, year = m.group(1), m.group(2)
        return f"{year}-{int(month):02d}", "exact"

    # Month YYYY
    m = _RE_MONTH_YEAR.match(text)
    if m:
        month_str = m.group(1).lower()
        month_num = _MONTH_NAMES.get(month_str)
        if month_num:
            return f"{m.group(2)}-{month_num}", "exact"

    # Year only
    m = _RE_YEAR_ONLY.match(text)
    if m:
        return f"{m.group(1)}-01", "year_only_approximated"

    logger.debug("Date unparseable: %r", raw)
    return None, "unparseable"
