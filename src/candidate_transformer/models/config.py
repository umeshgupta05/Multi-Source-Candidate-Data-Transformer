"""ProjectionConfig — runtime configuration for the output projection layer.

The config drives four capabilities:
1. Field subsetting — only emit listed fields.
2. Rename / remap — ``from`` path → output ``path``.
3. Per-field normalization override at projection time.
4. ``on_missing`` — ``"null"`` | ``"omit"`` | ``"error"``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class FieldSpec(BaseModel):
    """One field mapping in the projection config.

    Attributes:
        path: The key in the output JSON (e.g. ``"primary_email"``).
        from_path: Dot/bracket path into the canonical record
            (e.g. ``"emails[0]"``, ``"skills[].name"``).
        type: Expected output type — ``"string"``, ``"string[]"``,
            ``"number"``, ``"object"``, ``"object[]"``.
        required: If ``True`` and the value is missing, behaviour is
            determined by the top-level ``on_missing`` setting.
        normalize: Optional re-normalization to apply at projection time
            (e.g. ``"E.164"``, ``"canonical"``).
    """

    path: str = Field(
        ...,
        description="Output key in the projected JSON.",
    )
    from_path: str = Field(
        ...,
        alias="from",
        description="Dot/bracket path into the canonical record.",
    )
    type: str = Field(
        ...,
        description=(
            "Expected output type: 'string', 'string[]', 'number', "
            "'object', 'object[]'."
        ),
    )
    required: bool = False
    normalize: Optional[str] = None

    model_config = {"populate_by_name": True}


class ProjectionConfig(BaseModel):
    """Top-level runtime projection configuration.

    Loaded from a JSON file and passed to the projector + dynamic validator.
    """

    fields: list[FieldSpec]
    include_confidence: bool = Field(
        default=True,
        description="Whether to include overall_confidence in output.",
    )
    on_missing: Literal["null", "omit", "error"] = Field(
        default="null",
        description=(
            "What to do when a projected field resolves to None: "
            "'null' = keep key with null value, "
            "'omit' = drop key entirely, "
            "'error' = raise a validation error."
        ),
    )
