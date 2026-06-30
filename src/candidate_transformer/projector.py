"""Projector — config-driven projection layer.

Transforms a ``CanonicalRecord`` into a user-configured output shape using a
generic, recursive path-resolver.  This is the clean separation between the
internal canonical record and the user-facing output.

Supports:
1. Field subsetting — only emit fields listed in config.
2. Rename/remap — ``from`` path → arbitrary output ``path``.
3. Per-field normalize override at projection time.
4. ``on_missing`` — ``"null"`` | ``"omit"`` | ``"error"``.
"""

from __future__ import annotations

import re
import logging
from typing import Any

from candidate_transformer.models.canonical import CanonicalRecord
from candidate_transformer.models.config import ProjectionConfig, FieldSpec
from candidate_transformer.normalizers.phone import normalize_phone
from candidate_transformer.normalizers.skills import normalize_skill

logger = logging.getLogger(__name__)


class ProjectionError(Exception):
    """Raised when a required field is missing and ``on_missing == "error"``."""

    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


class Projector:
    """Project a CanonicalRecord into a config-driven output shape."""

    def project(
        self,
        record: CanonicalRecord,
        config: ProjectionConfig,
    ) -> dict[str, Any]:
        """Build the projected output from *record* using *config*.

        Returns a plain dict ready for JSON serialisation.
        """
        # Convert canonical record to dict for path-based access.
        canonical = record.model_dump(exclude={"field_confidences"})

        out: dict[str, Any] = {}
        errors: list[str] = []

        for field_spec in config.fields:
            value = get_by_path(canonical, field_spec.from_path)

            # Apply per-field normalization if specified.
            if field_spec.normalize and value is not None:
                value = self._apply_normalize(value, field_spec.normalize)

            # Coerce type.
            value = self._coerce_type(value, field_spec.type)

            # Handle missing values.
            if value is None:
                if field_spec.required and config.on_missing == "error":
                    errors.append(
                        f"Required field '{field_spec.path}' (from '{field_spec.from_path}') is missing."
                    )
                    continue
                elif config.on_missing == "omit":
                    continue
                # else: on_missing == "null" → set key to None.

            set_by_path(out, field_spec.path, value)

        # Attach confidence if requested.
        if config.include_confidence:
            out["overall_confidence"] = canonical.get("overall_confidence", 0.0)
            out["provenance"] = canonical.get("provenance", [])

        if errors:
            raise ProjectionError(
                field="multiple",
                message=f"Missing required fields: {'; '.join(errors)}",
            )

        return out

    # ------------------------------------------------------------------
    # Normalisation at projection time
    # ------------------------------------------------------------------

    def _apply_normalize(self, value: Any, normalize: str) -> Any:
        """Apply a named normalization to *value* at projection time."""
        if normalize == "E.164":
            if isinstance(value, str):
                return normalize_phone(value) or value
            elif isinstance(value, list):
                return [normalize_phone(str(v)) or v for v in value]

        elif normalize == "canonical":
            if isinstance(value, str):
                canonical, _ = normalize_skill(value)
                return canonical
            elif isinstance(value, list):
                return [normalize_skill(str(v))[0] for v in value]

        return value

    # ------------------------------------------------------------------
    # Type coercion
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_type(value: Any, target_type: str) -> Any:
        """Coerce *value* to the expected output type."""
        if value is None:
            return None

        if target_type == "string":
            if isinstance(value, list):
                return str(value[0]) if value else None
            return str(value)

        elif target_type == "string[]":
            if isinstance(value, list):
                return [str(v) for v in value]
            return [str(value)]

        elif target_type == "number":
            if isinstance(value, (int, float)):
                return value
            try:
                return float(value)
            except (ValueError, TypeError):
                return None

        elif target_type in ("object", "object[]"):
            return value

        return value


# ======================================================================
# Generic path resolver
# ======================================================================

# Regex for path segments: "field", "field[0]", "field[]"
_SEGMENT_RE = re.compile(r"^(\w+)(?:\[(\d+|)\])?$")


def get_by_path(data: dict | list, path: str) -> Any:
    """Resolve a dot/bracket path into *data*.

    Supports:
    - ``"skills[].name"`` — map over array, extract sub-field from each element.
    - ``"phones[0]"`` — index into array.
    - ``"location.country"`` — nested dot access.
    - ``"skills[].name"`` where the value is a list of dicts.

    Returns ``None`` if the path cannot be resolved.
    """
    segments = path.split(".")
    return _resolve(data, segments)


def _resolve(data: Any, segments: list[str]) -> Any:
    """Recursively resolve path segments."""
    if not segments:
        return data
    if data is None:
        return None

    seg = segments[0]
    rest = segments[1:]

    m = _SEGMENT_RE.match(seg)
    if not m:
        return None

    field_name = m.group(1)
    bracket = m.group(2)  # None = no bracket, "" = [], "0" = [0]

    # Get the field value.
    if isinstance(data, dict):
        value = data.get(field_name)
    else:
        return None

    if value is None:
        return None

    # Handle brackets.
    if bracket is not None:
        if bracket == "":
            # [] → map over array.
            if isinstance(value, list):
                results = [_resolve(item, rest) for item in value]
                return [r for r in results if r is not None]
            return None
        else:
            # [N] → index into array.
            idx = int(bracket)
            if isinstance(value, list) and 0 <= idx < len(value):
                return _resolve(value[idx], rest)
            return None

    # No bracket — plain field access.
    return _resolve(value, rest)


def set_by_path(data: dict, path: str, value: Any) -> None:
    """Set a value in *data* at the given dot-separated *path*.

    Creates intermediate dicts as needed.
    """
    parts = path.split(".")
    current = data

    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]

    current[parts[-1]] = value
