"""Deterministic parsing for common free-text location strings."""

from __future__ import annotations

import re
from dataclasses import dataclass

from candidate_transformer.normalizers.country import normalize_country


_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
_US_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME",
    "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}
_NON_LOCATION_TERMS = {
    "remote", "hybrid", "onsite", "on-site", "worldwide", "earth", "global",
    "open to relocate", "willing to relocate",
}
_LABEL_RE = re.compile(r"^\s*(?:location|based\s+in|current\s+location|address)\s*:\s*", re.I)
_BAD_CHARS_RE = re.compile(r"[@/]|\b(?:github|linkedin|portfolio|http|www)\b", re.I)


@dataclass(frozen=True)
class ParsedLocation:
    city: str | None = None
    region: str | None = None
    country: str | None = None


def parse_location_text(raw: str | None) -> ParsedLocation | None:
    """Parse clear free-text location strings without guessing.

    Supported examples:
    - ``San Francisco, CA`` -> city, region, country=US
    - ``London, United Kingdom`` -> city, country=GB
    - ``Bengaluru, Karnataka, India`` -> city, region, country=IN
    """
    if not raw or not raw.strip():
        return None

    text = _clean_location_candidate(raw)
    if not text:
        return None

    lower = text.lower()
    if lower in _NON_LOCATION_TERMS or _BAD_CHARS_RE.search(text):
        return None

    comma_parts = _parts(text)
    if len(comma_parts) >= 3:
        city, region, country_text = comma_parts[0], comma_parts[1], comma_parts[-1]
        country = normalize_country(country_text)
        if country:
            return ParsedLocation(city=city, region=_normalize_region(region, country), country=country)

    if len(comma_parts) == 2:
        city, second = comma_parts
        state = _normalize_us_state(second)
        if state:
            return ParsedLocation(city=city, region=state, country="US")

        country = normalize_country(second)
        if country:
            return ParsedLocation(city=city, country=country)

        return ParsedLocation(city=city, region=second)

    city, region, country = _parse_space_separated(text)
    if city or region or country:
        return ParsedLocation(city=city, region=region, country=country)

    return None


def location_segments_from_line(line: str) -> list[str]:
    """Return likely location-bearing chunks from a resume/README contact line."""
    if not line or not line.strip():
        return []
    normalized = re.sub(r"\s{2,}", " | ", line.strip())
    return [
        part.strip(" -")
        for part in re.split(r"\s*(?:\||;|/|\u2022|\u00b7)\s*", normalized)
        if part.strip(" -")
    ]


def _clean_location_candidate(raw: str) -> str:
    text = _LABEL_RE.sub("", raw.strip())
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -.,")


def _parts(text: str) -> list[str]:
    return [part.strip(" -") for part in text.split(",") if part.strip(" -")]


def _normalize_us_state(raw: str) -> str | None:
    text = raw.strip().strip(".")
    upper = text.upper()
    if upper in _US_STATE_CODES:
        return upper
    return _US_STATE_NAMES.get(text.lower())


def _normalize_region(raw: str, country: str) -> str:
    if country == "US":
        return _normalize_us_state(raw) or raw.strip()
    return raw.strip()


def _parse_space_separated(text: str) -> tuple[str | None, str | None, str | None]:
    state_match = re.match(r"^(.+?)\s+([A-Z]{2})$", text)
    if state_match:
        state = _normalize_us_state(state_match.group(2))
        if state:
            return state_match.group(1).strip(), state, "US"

    country_match = re.match(r"^(.+?)\s+([A-Za-z][A-Za-z .]{1,30})$", text)
    if country_match:
        maybe_country = normalize_country(country_match.group(2).strip())
        if maybe_country:
            return country_match.group(1).strip(), None, maybe_country

    return None, None, None
