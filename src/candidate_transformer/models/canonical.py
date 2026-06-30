"""CanonicalRecord — full-fidelity merged truth for one candidate.

This is the internal, *never-reshaped* representation.  The projector builds
user-facing output from this, but the CanonicalRecord itself is never mutated
or trimmed.  It always carries full provenance and per-field confidence.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Nested sub-models
# ---------------------------------------------------------------------------

class Location(BaseModel):
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = Field(
        default=None,
        description="ISO-3166 alpha-2 country code, e.g. 'US', 'IN'.",
    )


class Links(BaseModel):
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    sources: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    company: str
    title: str
    start: Optional[str] = Field(
        default=None,
        description="Start date in YYYY-MM format.",
    )
    end: Optional[str] = Field(
        default=None,
        description="End date in YYYY-MM format, or null for current.",
    )
    summary: Optional[str] = None


class Education(BaseModel):
    institution: str
    degree: Optional[str] = None
    field: Optional[str] = None
    end_year: Optional[int] = None


class ProvenanceEntry(BaseModel):
    """Describes *where an accepted value came from*.

    Only values that made it into the canonical record appear here — rejected /
    dropped values are logged to the CLI run summary, not provenance.
    """

    field: str
    source: str
    method: str


# ---------------------------------------------------------------------------
# Per-field confidence tracking (internal, not part of output schema)
# ---------------------------------------------------------------------------

class FieldConfidence(BaseModel):
    """Internal bookkeeping: tracks confidence + conflict flag per field."""

    field: str
    confidence: float = Field(ge=0.0, le=1.0)
    has_conflict: bool = False


# ---------------------------------------------------------------------------
# CanonicalRecord
# ---------------------------------------------------------------------------

# Fields that contribute to overall_confidence weighting.
_EXPECTED_FIELDS: list[str] = [
    "full_name",
    "emails",
    "phones",
    "location",
    "links",
    "headline",
    "years_experience",
    "skills",
    "experience",
    "education",
]


class CanonicalRecord(BaseModel):
    """The merged, full-fidelity candidate profile.

    ``candidate_id`` is generated deterministically:
    - ``sha256(normalized_primary_email)`` when an email exists.
    - ``sha256(normalized_full_name + '|' + normalized_company)`` as fallback.
    """

    candidate_id: str = Field(
        ...,
        description=(
            "Deterministic ID: sha256 of primary email, or name+company fallback."
        ),
    )
    full_name: Optional[str] = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(
        default_factory=list,
        description="Phone numbers in E.164 format.",
    )
    location: Location = Field(default_factory=Location)
    links: Links = Field(default_factory=Links)
    headline: Optional[str] = None
    years_experience: Optional[float] = None
    skills: list[Skill] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    overall_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Weighted average of per-field confidences, weighted by field "
            "population ratio."
        ),
    )

    # Internal tracking — excluded from serialised output.
    field_confidences: list[FieldConfidence] = Field(
        default_factory=list,
        exclude=True,
        description="Internal per-field confidence bookkeeping.",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_candidate_id(
        primary_email: str | None,
        full_name: str | None = None,
        company: str | None = None,
    ) -> str:
        """Create a deterministic candidate_id.

        Priority:
        1. sha256 of lowercased primary email.
        2. sha256 of ``name|company`` (both lowered, stripped).
        3. sha256 of whatever non-empty string is available.
        """
        if primary_email:
            seed = primary_email.strip().lower()
        elif full_name:
            company_part = (company or "").strip().lower()
            seed = f"{full_name.strip().lower()}|{company_part}"
        else:
            seed = "unknown"
        return hashlib.sha256(seed.encode()).hexdigest()[:16]

    def compute_overall_confidence(self) -> None:
        """Recompute ``overall_confidence`` from ``field_confidences``.

        Formula: weighted average where the weight is (populated fields /
        total expected fields).  A record with 3 strong fields and 8 nulls
        scores lower than one with 11 strong fields.
        """
        if not self.field_confidences:
            self.overall_confidence = 0.0
            return

        total_expected = len(_EXPECTED_FIELDS)
        populated = len(self.field_confidences)
        population_ratio = min(populated / total_expected, 1.0)

        avg_conf = sum(fc.confidence for fc in self.field_confidences) / populated
        self.overall_confidence = round(avg_conf * population_ratio, 4)
