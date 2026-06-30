"""RawFieldValue — one claim from one source about one field.

This is the universal intermediate representation between extractors and the
merge engine.  Every extractor produces a list of these, one per (candidate, field)
pair it was able to extract.  The merger then groups them by candidate and field
to decide the canonical value.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RawFieldValue(BaseModel):
    """A single extracted claim about a candidate field from one source.

    Attributes:
        candidate_key: A loose identifier used for entity resolution *before*
            a canonical candidate_id is minted.  Typically an email, phone, or
            name string.  The resolver will cluster RawFieldValues by matching
            these keys across sources.
        field: Canonical field name (e.g. ``"full_name"``, ``"skills"``).
        value: The extracted value — type depends on the field.
        source: Human-readable source tag, e.g. ``"recruiter_csv"``,
            ``"github_api"``, ``"resume_pdf"``.
        method: Extraction method tag, e.g. ``"direct_copy"``,
            ``"regex_extract"``, ``"section_parse"``, ``"api_field"``.
        raw_confidence: Base confidence from the source × method table.
        metadata: Arbitrary extra info (conflict notes, provenance details,
            line numbers, etc.).
    """

    candidate_key: str = Field(
        ...,
        description=(
            "Loose identifier for entity resolution — typically an email, "
            "phone, or name.  The resolver clusters RawFieldValues by "
            "matching these keys across sources."
        ),
    )
    field: str = Field(
        ...,
        description="Canonical field name, e.g. 'full_name', 'emails', 'skills'.",
    )
    value: Any = Field(
        ...,
        description="The extracted value.  Type varies by field.",
    )
    source: str = Field(
        ...,
        description="Source tag, e.g. 'recruiter_csv', 'github_api'.",
    )
    method: str = Field(
        ...,
        description=(
            "Extraction method, e.g. 'direct_copy', 'regex_extract', "
            "'section_parse', 'api_field'."
        ),
    )
    raw_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Base confidence from the source × method table.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra info (conflict notes, line numbers, etc.).",
    )
