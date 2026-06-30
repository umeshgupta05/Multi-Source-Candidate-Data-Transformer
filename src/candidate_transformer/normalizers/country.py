"""Country normalizer → ISO-3166 alpha-2 code.

Uses ``pycountry`` + a small alias table for common abbreviations and
informal names (e.g. "USA" → "US", "United States" → "US").

Unmappable → ``None``, never a guess.
"""

from __future__ import annotations

import logging

import pycountry

logger = logging.getLogger(__name__)

# Common aliases not handled cleanly by pycountry.fuzzy_search.
_ALIASES: dict[str, str] = {
    "usa": "US",
    "u.s.a.": "US",
    "u.s.": "US",
    "united states": "US",
    "united states of america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "great britain": "GB",
    "england": "GB",
    "scotland": "GB",
    "wales": "GB",
    "south korea": "KR",
    "north korea": "KP",
    "russia": "RU",
    "taiwan": "TW",
    "vietnam": "VN",
    "czech republic": "CZ",
    "ivory coast": "CI",
}


def normalize_country(raw: str | None) -> str | None:
    """Normalise *raw* country string to ISO-3166 alpha-2 code.

    Returns ``None`` if the country cannot be mapped — never guesses.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Already a valid alpha-2 code?
    upper = text.upper()
    if len(upper) == 2:
        try:
            pycountry.countries.get(alpha_2=upper)
            return upper
        except (KeyError, AttributeError):
            pass

    # Already a valid alpha-3 code?
    if len(upper) == 3:
        try:
            country = pycountry.countries.get(alpha_3=upper)
            if country:
                return country.alpha_2
        except (KeyError, AttributeError):
            pass

    # Check alias table.
    lower = text.lower()
    if lower in _ALIASES:
        return _ALIASES[lower]

    # Try pycountry lookup by name.
    try:
        country = pycountry.countries.lookup(text)
        return country.alpha_2
    except LookupError:
        pass

    # Try fuzzy search (pycountry ≥ 22.x).
    try:
        results = pycountry.countries.search_fuzzy(text)
        if results:
            return results[0].alpha_2
    except LookupError:
        pass

    logger.debug("Country unmappable: %r", raw)
    return None
