"""ATSExtractor — parses ATS (Applicant Tracking System) JSON blobs.

The ATS JSON uses its own field names that do NOT match the canonical schema.
A configurable field-mapping dict translates them.

Edge-case handling:
- Missing / malformed file → return empty list.
- Per-field soft failure: one bad field skips that field, not the whole record.
- Unexpected / renamed field names → unmapped fields are silently ignored.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from candidate_transformer.models.raw import RawFieldValue

from .base import BaseExtractor
from ._location_parser import parse_location_text

logger = logging.getLogger(__name__)

# ATS field name → (canonical field name, is_list?)
_FIELD_MAP: dict[str, tuple[str, bool]] = {
    "applicant_name": ("full_name", False),
    "contact_email": ("emails", False),
    "contact_phone": ("phones", False),
    "current_employer": ("current_company", False),
    "job_title": ("title", False),
    "location_city": ("location.city", False),
    "location_state": ("location.region", False),
    "location_country": ("location.country", False),
    "skills_list": ("skills", True),
    "years_of_experience": ("years_experience", False),
}
_FIELD_ALIASES: dict[str, tuple[str, bool]] = {
    "name": ("full_name", False),
    "full_name": ("full_name", False),
    "candidate_name": ("full_name", False),
    "email": ("emails", False),
    "email_address": ("emails", False),
    "primary_email": ("emails", False),
    "phone": ("phones", False),
    "phone_number": ("phones", False),
    "mobile": ("phones", False),
    "company": ("current_company", False),
    "employer": ("current_company", False),
    "current_company": ("current_company", False),
    "title": ("title", False),
    "role": ("title", False),
    "position": ("title", False),
    "city": ("location.city", False),
    "state": ("location.region", False),
    "region": ("location.region", False),
    "country": ("location.country", False),
    "skills": ("skills", True),
    "skillset": ("skills", True),
    "tech_stack": ("skills", True),
    "experience_years": ("years_experience", False),
    "yoe": ("years_experience", False),
}
_NESTED_FIELD_PATHS: dict[str, tuple[str, bool, list[tuple[str, ...]]]] = {
    "full_name": ("full_name", False, [("profile", "name"), ("personal", "name"), ("candidate", "name")]),
    "emails": ("emails", True, [("contact", "email"), ("contact", "emails"), ("profile", "email")]),
    "phones": ("phones", True, [("contact", "phone"), ("contact", "phones"), ("profile", "phone")]),
    "location.city": ("location.city", False, [("location", "city"), ("address", "city")]),
    "location.region": ("location.region", False, [("location", "state"), ("location", "region"), ("address", "state")]),
    "location.country": ("location.country", False, [("location", "country"), ("address", "country")]),
}
_LIST_SPLIT_RE = re.compile(r"[,;|]")

_BASE_CONFIDENCE = 0.95


class ATSExtractor(BaseExtractor):
    """Extract candidate data from an ATS JSON file."""

    source_name = "ats_json"

    def extract(self, source_path: str | Path) -> list[RawFieldValue]:
        path = Path(source_path)
        if not self._check_file(path):
            return []

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[%s] Failed to parse JSON %s: %s", self.source_name, path, exc)
            return []

        applicants = data if isinstance(data, list) else _first_list(data, ("applicants", "candidates", "records", "data"))
        if not isinstance(applicants, list):
            logger.warning("[%s] Expected list of applicants in %s", self.source_name, path)
            return []

        results: list[RawFieldValue] = []
        for idx, record in enumerate(applicants):
            if not isinstance(record, dict):
                logger.warning("[%s] Applicant #%d is not a dict — skipping.", self.source_name, idx)
                continue

            try:
                rfvs = self._extract_record(record, idx)
                results.extend(rfvs)
            except Exception:
                logger.exception(
                    "[%s] Unexpected error extracting applicant #%d — skipping record.",
                    self.source_name,
                    idx,
                )

        logger.info("[%s] Extracted %d field values from %s", self.source_name, len(results), path)
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_record(self, record: dict[str, Any], idx: int) -> list[RawFieldValue]:
        """Extract RawFieldValues from a single ATS applicant record.

        Soft-fails per field — one bad field does not null out the whole candidate.
        """
        # Determine candidate key.
        email = _first_text(record, ("contact_email", "email", "email_address", "primary_email")) or _first_nested_text(
            record, [("contact", "email"), ("profile", "email")]
        )
        name = _first_text(record, ("applicant_name", "name", "full_name", "candidate_name")) or _first_nested_text(
            record, [("profile", "name"), ("personal", "name"), ("candidate", "name")]
        )
        email = (email or "").strip().lower()
        name = (name or "").strip().lower()
        candidate_key = email or name
        if not candidate_key:
            logger.warning("[%s] Applicant #%d has no email or name — skipping.", self.source_name, idx)
            return []

        rfvs: list[RawFieldValue] = []

        # --- Mapped scalar / list fields ---
        for ats_field, (canonical_field, is_list) in {**_FIELD_MAP, **_FIELD_ALIASES}.items():
            value = record.get(ats_field)
            if _is_empty(value):
                continue

            try:
                for item in _coerce_values(value, split=is_list):
                    rfvs.append(
                        self._make_rfv(
                            candidate_key=candidate_key,
                            field=canonical_field,
                            value=item,
                            source=self.source_name,
                            method="direct_copy",
                            confidence=_BASE_CONFIDENCE,
                        )
                    )
            except Exception:
                logger.warning(
                    "[%s] Failed to extract field '%s' for applicant #%d — skipping field.",
                    self.source_name,
                    ats_field,
                    idx,
                )

        for canonical_field, is_list, paths in _NESTED_FIELD_PATHS.values():
            for path in paths:
                value = _get_nested(record, path)
                if _is_empty(value):
                    continue
                for item in _coerce_values(value, split=is_list):
                    rfvs.append(self._make_rfv(
                        candidate_key=candidate_key,
                        field=canonical_field,
                        value=item,
                        source=self.source_name,
                        method="direct_copy",
                        confidence=_BASE_CONFIDENCE,
                    ))
                break

        for raw_location_field in ("location", "address"):
            raw_location = record.get(raw_location_field)
            if not isinstance(raw_location, str) or not raw_location.strip():
                continue
            location = parse_location_text(raw_location)
            if not location:
                continue
            for field, value in (
                ("location.city", location.city),
                ("location.region", location.region),
                ("location.country", location.country),
            ):
                if value:
                    rfvs.append(self._make_rfv(
                        candidate_key=candidate_key,
                        field=field,
                        value=value,
                        source=self.source_name,
                        method="location_parse",
                        confidence=_BASE_CONFIDENCE,
                    ))
            break

        # --- Education ---
        for edu in _coerce_sequence(record.get("education") or record.get("educations") or record.get("schools")):
            if not isinstance(edu, dict):
                continue
            try:
                edu_obj = {
                    "institution": edu.get("school") or edu.get("institution") or edu.get("university") or "",
                    "degree": edu.get("degree_type") or edu.get("degree"),
                    "field": edu.get("major") or edu.get("field") or edu.get("field_of_study"),
                    "end_year": edu.get("graduation_year") or edu.get("end_year") or edu.get("year"),
                }
                if edu_obj["institution"]:
                    rfvs.append(
                        self._make_rfv(
                            candidate_key=candidate_key,
                            field="education",
                            value=edu_obj,
                            source=self.source_name,
                            method="direct_copy",
                            confidence=_BASE_CONFIDENCE,
                        )
                    )
            except Exception:
                logger.warning(
                    "[%s] Bad education entry in applicant #%d — skipping.",
                    self.source_name,
                    idx,
                )

        # --- Work history → experience ---
        for job in _coerce_sequence(record.get("work_history") or record.get("experience") or record.get("experiences") or record.get("jobs")):
            if not isinstance(job, dict):
                continue
            try:
                exp_obj = {
                    "company": job.get("employer") or job.get("company") or job.get("organization") or "",
                    "title": job.get("role") or job.get("title") or job.get("position") or "",
                    "start": job.get("start_date") or job.get("start"),
                    "end": job.get("end_date") or job.get("end"),
                    "summary": job.get("summary") or job.get("description"),
                }
                if exp_obj["company"] or exp_obj["title"]:
                    rfvs.append(
                        self._make_rfv(
                            candidate_key=candidate_key,
                            field="experience",
                            value=exp_obj,
                            source=self.source_name,
                            method="direct_copy",
                            confidence=_BASE_CONFIDENCE,
                        )
                    )
            except Exception:
                logger.warning(
                    "[%s] Bad work_history entry in applicant #%d — skipping.",
                    self.source_name,
                    idx,
                )

        return rfvs


def _first_list(data: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _first_nested_text(record: dict[str, Any], paths: list[tuple[str, ...]]) -> str | None:
    for path in paths:
        value = _get_nested(record, path)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _get_nested(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


def _coerce_sequence(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _coerce_values(value: Any, split: bool) -> list[Any]:
    if isinstance(value, list):
        values = value
    elif split and isinstance(value, str):
        values = _LIST_SPLIT_RE.split(value)
    else:
        values = [value]
    return [item.strip() if isinstance(item, str) else item for item in values if not _is_empty(item)]
