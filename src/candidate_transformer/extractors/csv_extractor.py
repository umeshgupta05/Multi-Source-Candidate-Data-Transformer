"""CSVExtractor — parses recruiter CSV exports.

Expected CSV columns: ``name, email, phone, current_company, title``.

Edge-case handling:
- Missing columns → skip the whole row (log warning with row number).
- Extra columns → silently ignored.
- Empty cell values → skip that field, don't emit a RawFieldValue for it.
- Empty / missing file → return empty list.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from candidate_transformer.models.raw import RawFieldValue

from .base import BaseExtractor
from ._location_parser import parse_location_text

logger = logging.getLogger(__name__)

# Column name → canonical field name mapping.
_COLUMN_MAP: dict[str, str] = {
    "name": "full_name",
    "email": "emails",
    "phone": "phones",
    "current_company": "current_company",
    "title": "title",
    "location": "location.city",
    "city": "location.city",
    "state": "location.region",
    "country": "location.country",
    "linkedin": "links.linkedin",
    "github": "links.github",
    "portfolio": "links.portfolio",
    "skills": "skills",
    "years_experience": "years_experience",
}
_COLUMN_ALIASES: dict[str, str] = {
    "candidate": "name",
    "candidate_name": "name",
    "full_name": "name",
    "applicant": "name",
    "applicant_name": "name",
    "email_address": "email",
    "primary_email": "email",
    "contact_email": "email",
    "mobile": "phone",
    "phone_number": "phone",
    "contact_phone": "phone",
    "company": "current_company",
    "employer": "current_company",
    "current_employer": "current_company",
    "job_title": "title",
    "role": "title",
    "position": "title",
    "current_title": "title",
    "location_city": "city",
    "location_state": "state",
    "region": "state",
    "location_country": "country",
    "linkedin_url": "linkedin",
    "github_url": "github",
    "portfolio_url": "portfolio",
    "website": "portfolio",
    "personal_site": "portfolio",
    "skills_list": "skills",
    "tech_stack": "skills",
    "years_of_experience": "years_experience",
    "yoe": "years_experience",
}
_LIST_FIELDS = {"skills", "emails", "phones"}
_SPLIT_RE = re.compile(r"[,;|]")

# Structured direct-copy base confidence.
_BASE_CONFIDENCE = 0.95


class CSVExtractor(BaseExtractor):
    """Extract candidate data from a recruiter CSV file."""

    source_name = "recruiter_csv"

    def extract(self, source_path: str | Path) -> list[RawFieldValue]:
        path = Path(source_path)
        if not self._check_file(path):
            return []

        results: list[RawFieldValue] = []

        try:
            with path.open(newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)

                if reader.fieldnames is None:
                    logger.warning("[%s] CSV has no header row: %s", self.source_name, path)
                    return []

                # Normalise header names (lowercase, strip whitespace).
                header_map: dict[str, str] = {}
                for raw_col in reader.fieldnames:
                    clean = _canonical_column(raw_col)
                    if clean in _COLUMN_MAP:
                        header_map[raw_col] = clean

                required_cols = {"name", "email"}
                missing_cols = required_cols - set(header_map.values())
                if missing_cols:
                    logger.warning(
                        "[%s] CSV missing identity columns %s in %s",
                        self.source_name,
                        missing_cols,
                        path,
                    )

                for row_idx, row in enumerate(reader, start=2):  # row 1 is header
                    # Determine candidate key — prefer email, fall back to name.
                    email_val = self._cell(row, header_map, "email")
                    name_val = self._cell(row, header_map, "name")

                    if not email_val and not name_val:
                        logger.warning(
                            "[%s] Row %d: no email and no name — skipping row.",
                            self.source_name,
                            row_idx,
                        )
                        continue

                    candidate_key = (email_val or name_val or "").strip().lower()

                    for raw_col, clean_col in header_map.items():
                        canonical_field = _COLUMN_MAP[clean_col]
                        cell = (row.get(raw_col) or "").strip()
                        if not cell:
                            continue

                        values = _split_cell(cell) if clean_col in _LIST_FIELDS else [cell]
                        for value in values:
                            if clean_col == "location":
                                location = parse_location_text(str(value))
                                if location:
                                    for field, loc_value in (
                                        ("location.city", location.city),
                                        ("location.region", location.region),
                                        ("location.country", location.country),
                                    ):
                                        if loc_value:
                                            results.append(
                                                self._make_rfv(
                                                    candidate_key=candidate_key,
                                                    field=field,
                                                    value=loc_value,
                                                    source=self.source_name,
                                                    method="location_parse",
                                                    confidence=_BASE_CONFIDENCE,
                                                    row=row_idx,
                                                )
                                            )
                                    continue

                            results.append(
                                self._make_rfv(
                                    candidate_key=candidate_key,
                                    field=canonical_field,
                                    value=value,
                                    source=self.source_name,
                                    method="direct_copy",
                                    confidence=_BASE_CONFIDENCE,
                                    row=row_idx,
                                )
                            )

        except Exception:
            logger.exception("[%s] Failed to read CSV %s", self.source_name, path)

        logger.info(
            "[%s] Extracted %d field values from %s", self.source_name, len(results), path
        )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cell(row: dict, header_map: dict[str, str], target_clean: str) -> str | None:
        """Get the cell value for a target clean column name."""
        for raw_col, clean_col in header_map.items():
            if clean_col == target_clean:
                val = (row.get(raw_col) or "").strip()
                return val if val else None
        return None


def _canonical_column(raw_col: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", raw_col.strip().lower()).strip("_")
    return _COLUMN_ALIASES.get(clean, clean)


def _split_cell(value: str) -> list[str]:
    items = [part.strip() for part in _SPLIT_RE.split(value) if part.strip()]
    return items or [value.strip()]
