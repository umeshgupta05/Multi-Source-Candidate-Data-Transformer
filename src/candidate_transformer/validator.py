"""Dynamic Validator — derives validation schema from the projection config.

The validator does NOT use a fixed Pydantic model.  Instead, it builds
validation rules from the ``FieldSpec`` list in the active config.

Key design point: "The validator doesn't assume a schema — it derives one
from whatever config was passed in."
"""

from __future__ import annotations

import logging
from typing import Any

from candidate_transformer.models.config import ProjectionConfig

logger = logging.getLogger(__name__)


class ValidationError:
    """One validation failure."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message

    def __repr__(self) -> str:
        return f"ValidationError(field={self.field!r}, message={self.message!r})"

    def __str__(self) -> str:
        return f"[{self.field}] {self.message}"


class Validator:
    """Dynamic validator that derives its schema from a ProjectionConfig."""

    def validate(
        self,
        projected: dict[str, Any],
        config: ProjectionConfig,
    ) -> list[ValidationError]:
        """Validate *projected* output against *config*.

        Returns a list of ``ValidationError`` — empty list means valid.
        Does not fail on first error; collects all issues.
        """
        errors: list[ValidationError] = []

        for field_spec in config.fields:
            value = self._get_value(projected, field_spec.path)

            # --- Check presence ---
            if value is None:
                if field_spec.required:
                    if config.on_missing == "error":
                        errors.append(ValidationError(
                            field=field_spec.path,
                            message=f"Required field is missing (on_missing='error').",
                        ))
                    elif config.on_missing == "null":
                        # Value should be explicitly null — check key exists.
                        if not self._key_exists(projected, field_spec.path):
                            errors.append(ValidationError(
                                field=field_spec.path,
                                message="Required field key is absent (expected null value).",
                            ))
                elif config.on_missing == "omit":
                    # If on_missing is "omit", the key should NOT be present.
                    if self._key_exists(projected, field_spec.path):
                        errors.append(ValidationError(
                            field=field_spec.path,
                            message="Field is null but key is present (on_missing='omit').",
                        ))
                continue

            # --- Check type ---
            type_error = self._check_type(value, field_spec.type, field_spec.path)
            if type_error:
                errors.append(type_error)

        # --- Check confidence if expected ---
        if config.include_confidence:
            if "overall_confidence" not in projected:
                errors.append(ValidationError(
                    field="overall_confidence",
                    message="include_confidence is true but overall_confidence is missing.",
                ))
            elif not isinstance(projected.get("overall_confidence"), (int, float)):
                errors.append(ValidationError(
                    field="overall_confidence",
                    message="overall_confidence must be a number.",
                ))
            if "provenance" not in projected:
                errors.append(ValidationError(
                    field="provenance",
                    message="include_confidence is true but provenance is missing.",
                ))

        if errors:
            logger.warning("Validation found %d errors.", len(errors))
            for err in errors:
                logger.warning("  %s", err)
        else:
            logger.info("Validation passed.")

        return errors

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_value(self, data: dict, path: str) -> Any:
        """Get a value from nested dict by dot-separated path."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _key_exists(self, data: dict, path: str) -> bool:
        """Check if a key exists in nested dict (even if value is None)."""
        parts = path.split(".")
        current = data
        for part in parts[:-1]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False
        return isinstance(current, dict) and parts[-1] in current

    def _check_type(self, value: Any, expected_type: str, field: str) -> ValidationError | None:
        """Check that *value* matches *expected_type*."""
        if expected_type == "string":
            if not isinstance(value, str):
                return ValidationError(
                    field=field,
                    message=f"Expected string, got {type(value).__name__}.",
                )

        elif expected_type == "string[]":
            if not isinstance(value, list):
                return ValidationError(
                    field=field,
                    message=f"Expected string[], got {type(value).__name__}.",
                )
            for i, item in enumerate(value):
                if not isinstance(item, str):
                    return ValidationError(
                        field=f"{field}[{i}]",
                        message=f"Expected string, got {type(item).__name__}.",
                    )

        elif expected_type == "number":
            if not isinstance(value, (int, float)):
                return ValidationError(
                    field=field,
                    message=f"Expected number, got {type(value).__name__}.",
                )

        elif expected_type == "object":
            if not isinstance(value, dict):
                return ValidationError(
                    field=field,
                    message=f"Expected object, got {type(value).__name__}.",
                )

        elif expected_type == "object[]":
            if not isinstance(value, list):
                return ValidationError(
                    field=field,
                    message=f"Expected object[], got {type(value).__name__}.",
                )

        return None
