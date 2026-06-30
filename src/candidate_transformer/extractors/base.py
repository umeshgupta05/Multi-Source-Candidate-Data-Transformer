"""BaseExtractor — abstract base class for all source extractors.

Every extractor must implement ``extract()`` and return a flat list of
``RawFieldValue`` objects.  The base class provides common utilities for
file-existence checks and error wrapping.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from candidate_transformer.models.raw import RawFieldValue

logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    """Abstract base for all extractors.

    Subclasses must implement :meth:`extract`.
    """

    #: Human-readable source tag (set in each subclass).
    source_name: str = "unknown"

    @abstractmethod
    def extract(self, source_path: str | Path) -> list[RawFieldValue]:
        """Extract raw field values from *source_path*.

        Must never raise on bad/missing input — return an empty list and log
        a warning instead.
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _check_file(self, path: Path) -> bool:
        """Return True if *path* exists and is a file; log warning otherwise."""
        if not path.exists():
            logger.warning("[%s] Source file not found: %s", self.source_name, path)
            return False
        if not path.is_file():
            logger.warning("[%s] Not a file: %s", self.source_name, path)
            return False
        return True

    @staticmethod
    def _make_rfv(
        candidate_key: str,
        field: str,
        value,
        source: str,
        method: str,
        confidence: float,
        **meta,
    ) -> RawFieldValue:
        """Convenience factory for ``RawFieldValue``."""
        return RawFieldValue(
            candidate_key=candidate_key,
            field=field,
            value=value,
            source=source,
            method=method,
            raw_confidence=confidence,
            metadata=meta,
        )
