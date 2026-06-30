"""Phone normalizer -> E.164 format via the ``phonenumbers`` library.

Rules:
- ``normalize_phone`` keeps the legacy single-region behavior for existing
  callers.
- ``normalize_phone_with_candidates`` supports merger use cases where location
  fields can provide ordered phone-region candidates.
- If the phone can't be parsed at all -> return ``None`` (drop from phones[],
  log rejection to CLI summary - NOT provenance).
"""

from __future__ import annotations

import logging
import os
import re

import phonenumbers

logger = logging.getLogger(__name__)


def normalize_phone(raw: str, default_region: str | None = None) -> str | None:
    """Normalise *raw* phone string to E.164 format.

    Returns ``None`` if the phone cannot be parsed — the caller should log
    the rejection and drop it from ``phones[]``.
    """
    if not raw or not raw.strip():
        return None

    region = default_region or "US"

    try:
        parsed = phonenumbers.parse(raw.strip(), region)
    except phonenumbers.NumberParseException:
        logger.debug("Phone unparseable (region=%s): %r", region, raw)
        return None

    if not phonenumbers.is_valid_number(parsed):
        logger.debug("Phone invalid (region=%s): %r", region, raw)
        return None

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def _digit_groups(value: str) -> list[str]:
    return re.findall(r"\d+", value)


def _matches_user_grouping(raw: str, parsed: phonenumbers.PhoneNumber) -> bool:
    """Reject region guesses that reinterpret explicitly grouped local numbers.

    ``phonenumbers`` can consider the same national-looking digits valid in
    multiple regions. When a user supplied separators, compare their digit-group
    layout to the parsed region's national formatting so a UK-style
    ``07911 123456`` is not silently accepted as an Indian ``079 1112 3456``.
    Ungrouped values are allowed through because they provide no layout signal.
    """
    raw_groups = _digit_groups(raw)
    if len(raw_groups) <= 1:
        return True

    national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
    return [len(group) for group in raw_groups] == [len(group) for group in _digit_groups(national)]


def normalize_phone_with_candidates(
    raw: str,
    candidate_regions: list[str],
    fallback_region: str = "US",
) -> tuple[str | None, str | None]:
    """Normalize a phone by validating increasingly broad region guesses.

    Returns ``(e164_value_or_None, region_used_or_None)``. ``region_used`` is
    ``None`` for an already-international number or an unparseable value.
    """
    if not raw or not raw.strip():
        return None, None

    cleaned = raw.strip()

    try:
        parsed = phonenumbers.parse(cleaned, None)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164), None
    except phonenumbers.NumberParseException:
        logger.debug("Phone not directly parseable without region: %r", raw)

    seen_regions: set[str] = set()
    for region in candidate_regions:
        normalized_region = (region or "").strip().upper()
        if not normalized_region or normalized_region in seen_regions:
            continue
        seen_regions.add(normalized_region)
        try:
            parsed = phonenumbers.parse(cleaned, normalized_region)
        except phonenumbers.NumberParseException:
            logger.debug("Phone unparseable (region=%s): %r", normalized_region, raw)
            continue
        if phonenumbers.is_valid_number(parsed) and _matches_user_grouping(cleaned, parsed):
            return (
                phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
                normalized_region,
            )
        logger.debug("Phone invalid (region=%s): %r", normalized_region, raw)

    env_fallback = os.getenv("PHONE_DEFAULT_REGION")
    final_fallback = (env_fallback or fallback_region or "US").strip().upper()
    if final_fallback and final_fallback not in seen_regions:
        try:
            parsed = phonenumbers.parse(cleaned, final_fallback)
        except phonenumbers.NumberParseException:
            logger.debug("Phone unparseable (fallback_region=%s): %r", final_fallback, raw)
            return None, None
        if phonenumbers.is_valid_number(parsed) and _matches_user_grouping(cleaned, parsed):
            return (
                phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
                final_fallback,
            )
        logger.debug("Phone invalid (fallback_region=%s): %r", final_fallback, raw)

    return None, None
