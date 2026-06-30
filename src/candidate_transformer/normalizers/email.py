"""Email normalizer — lowercase, trim, validate format.

Rules:
- Lowercase + trim.
- Validate with a reasonable regex (not RFC-perfect, but catches garbage).
- Malformed strings → ``None`` (caller logs rejection to CLI summary, NOT
  provenance).
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# Reasonable email regex — catches most real addresses, rejects obvious garbage.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)


def normalize_email(raw: str | None) -> str | None:
    """Normalise *raw* email: lowercase, trim, validate format.

    Returns ``None`` for malformed strings — caller should log the rejection.
    """
    if not raw or not raw.strip():
        return None

    email = raw.strip().lower()

    if not _EMAIL_RE.match(email):
        logger.debug("Email malformed, rejecting: %r", raw)
        return None

    return email
