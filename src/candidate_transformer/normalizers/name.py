"""Name normalizer — title-case, trim, collapse whitespace.

Rules:
- Title-case, trim leading/trailing whitespace.
- Collapse internal whitespace to single spaces.
- Never invent a missing first/last name from an email username — that's the
  "confidently wrong" trap the spec warns about.
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_MULTI_SPACE = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str | None:
    """Normalise *raw* name: title-case, trim, collapse whitespace.

    Returns ``None`` if the input is empty/whitespace.
    """
    if not raw or not raw.strip():
        return None

    name = raw.strip()
    name = _MULTI_SPACE.sub(" ", name)
    name = name.title()

    return name
