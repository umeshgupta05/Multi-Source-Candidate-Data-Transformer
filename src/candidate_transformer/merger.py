"""Merger & Confidence Scorer — the heart of the pipeline.

Takes a cluster of ``RawFieldValue`` objects (all belonging to the same
resolved candidate) and produces a single ``CanonicalRecord`` with:
- Per-field merge decisions based on source priority.
- Per-field confidence scores with agreement bonuses and conflict caps.
- Provenance entries for every accepted value.
- Deterministic ``years_experience`` derivation from experience dates.

Merge policy:
- Single source → use it, confidence = base confidence.
- Multiple agree → use it, confidence = min(1.0, max(bases) + AGREEMENT_BONUS).
- Multiple disagree → pick highest-priority source, cap confidence at
  CONFLICT_CAP, add conflict flag in provenance.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, date

from candidate_transformer.models.raw import RawFieldValue
from candidate_transformer.models.canonical import (
    CanonicalRecord,
    Location,
    Links,
    Skill,
    Experience,
    Education,
    ProvenanceEntry,
    FieldConfidence,
)
from candidate_transformer.normalizers.email import normalize_email
from candidate_transformer.normalizers.phone import normalize_phone, normalize_phone_with_candidates
from candidate_transformer.normalizers.name import normalize_name
from candidate_transformer.normalizers.country import normalize_country
from candidate_transformer.normalizers.skills import normalize_skill
from candidate_transformer.normalizers.date import normalize_date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGREEMENT_BONUS = 0.10
CONFLICT_CAP = 0.60

# Source priority by field type (higher index = lower priority).
_SOURCE_PRIORITY: dict[str, list[str]] = {
    "full_name":        ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
    "emails":           ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
    "phones":           ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
    "current_company":  ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
    "title":            ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
    "skills":           ["github_api", "github_readme_llm", "github_readme_regex", "resume_pdf", "resume_llm", "ats_json"],
    "headline":         ["resume_pdf", "resume_llm", "github_readme_llm", "github_readme_regex", "github_api", "ats_json"],
    "years_experience": ["resume_pdf", "resume_llm", "github_readme_llm", "github_readme_regex", "github_api", "ats_json"],
    "location.city":    ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
    "location.region":  ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
    "location.country": ["recruiter_csv", "ats_json", "resume_pdf", "resume_llm", "github_api", "github_readme_llm", "github_readme_regex"],
}


def _source_rank(field: str, source: str) -> int:
    """Lower rank = higher priority.  Unknown sources get max rank."""
    priority_list = _SOURCE_PRIORITY.get(field, [])
    try:
        return priority_list.index(source)
    except ValueError:
        return len(priority_list)


def _candidate_phone_regions(by_field: dict) -> list[str]:
    """Collect normalized candidate country regions ordered by confidence."""
    country_rfvs = by_field.get("location.country", [])
    ordered = sorted(country_rfvs, key=lambda rfv: rfv.raw_confidence, reverse=True)

    regions: list[str] = []
    seen: set[str] = set()
    for rfv in ordered:
        region = normalize_country(str(rfv.value)) if rfv.value is not None else None
        if region and region not in seen:
            seen.add(region)
            regions.append(region)
    return regions


def _attach_phone_region_metadata(
    raw: str,
    rfv: RawFieldValue,
    phone_region_by_raw: dict[str, str | None],
    candidate_regions: list[str],
) -> None:
    region_used = phone_region_by_raw.get(raw)
    if region_used and region_used in candidate_regions:
        rfv.metadata["region_used"] = region_used
        rfv.metadata["region_source"] = "inferred_from_location"


# ---------------------------------------------------------------------------
# Run summary tracking (rejection / conflict log for CLI output)
# ---------------------------------------------------------------------------

class MergeStats:
    """Collects stats and rejections during a merge run."""

    def __init__(self):
        self.conflicts: list[dict] = []
        self.rejections: list[dict] = []
        self.null_fields: list[str] = []

    def add_conflict(self, field: str, sources: list[str], chosen_source: str):
        unique_sources = list(dict.fromkeys(sources))
        self.conflicts.append({
            "field": field,
            "sources": unique_sources,
            "chosen": chosen_source,
        })

    def add_rejection(self, field: str, value: str, reason: str, source: str):
        self.rejections.append({
            "field": field,
            "value": value,
            "reason": reason,
            "source": source,
        })

    def add_null(self, field: str):
        self.null_fields.append(field)


# ---------------------------------------------------------------------------
# Merger
# ---------------------------------------------------------------------------

class Merger:
    """Merges a cluster of RawFieldValues into a single CanonicalRecord."""

    def merge(
        self, cluster_rfvs: list[RawFieldValue], stats: MergeStats | None = None
    ) -> CanonicalRecord:
        """Merge all RFVs for one resolved candidate into a CanonicalRecord."""
        if stats is None:
            stats = MergeStats()

        # Group RFVs by field.
        by_field: dict[str, list[RawFieldValue]] = defaultdict(list)
        for rfv in cluster_rfvs:
            by_field[rfv.field].append(rfv)

        phone_regions = _candidate_phone_regions(by_field)
        provenance: list[ProvenanceEntry] = []
        field_confidences: list[FieldConfidence] = []

        # --- Scalar fields ---
        full_name = self._merge_scalar(
            "full_name", by_field.get("full_name", []),
            normalizer=normalize_name, stats=stats,
        )
        if full_name:
            provenance.append(full_name[2])
            field_confidences.append(full_name[3])

        # --- Emails (list, deduplicated) ---
        emails_result = self._merge_list_normalized(
            "emails", by_field.get("emails", []),
            normalizer=normalize_email, stats=stats,
        )
        emails = emails_result[0]
        provenance.extend(emails_result[1])
        if emails_result[2]:
            field_confidences.append(emails_result[2])

        # --- Phones (list, deduplicated, E.164) ---
        phone_region_by_raw: dict[str, str | None] = {}

        def normalize_candidate_phone(raw: str) -> str | None:
            normalized, region_used = normalize_phone_with_candidates(raw, phone_regions)
            if normalized is not None:
                phone_region_by_raw[raw] = region_used
            return normalized

        phones_result = self._merge_list_normalized(
            "phones", by_field.get("phones", []),
            normalizer=normalize_candidate_phone, stats=stats,
            metadata_callback=lambda raw, rfv: _attach_phone_region_metadata(
                raw, rfv, phone_region_by_raw, phone_regions
            ),
        )
        phones = phones_result[0]
        provenance.extend(phones_result[1])
        if phones_result[2]:
            field_confidences.append(phones_result[2])

        # --- Location ---
        location, loc_prov, loc_confs = self._merge_location(by_field, stats)
        provenance.extend(loc_prov)
        field_confidences.extend(loc_confs)

        # --- Links ---
        links, links_prov = self._merge_links(by_field, stats)
        provenance.extend(links_prov)

        # --- Headline ---
        headline = self._merge_scalar(
            "headline", by_field.get("headline", []),
            stats=stats,
        )
        if headline:
            provenance.append(headline[2])
            field_confidences.append(headline[3])

        # --- Title (mapped to headline if headline is missing) ---
        title_result = self._merge_scalar(
            "title", by_field.get("title", []),
            stats=stats,
        )

        # --- Current company ---
        company_result = self._merge_scalar(
            "current_company", by_field.get("current_company", []),
            stats=stats,
        )

        # --- Skills ---
        skills, skills_prov, skills_conf = self._merge_skills(
            by_field.get("skills", []), stats
        )
        provenance.extend(skills_prov)
        if skills_conf:
            field_confidences.append(skills_conf)

        # --- Experience ---
        experience, exp_prov = self._merge_experience(by_field.get("experience", []))
        provenance.extend(exp_prov)
        if experience:
            field_confidences.append(FieldConfidence(field="experience", confidence=0.85))

        # --- Education ---
        education, edu_prov = self._merge_education(by_field.get("education", []))
        provenance.extend(edu_prov)
        if education:
            field_confidences.append(FieldConfidence(field="education", confidence=0.85))

        # --- Years of experience ---
        years_exp = self._merge_scalar(
            "years_experience", by_field.get("years_experience", []),
            stats=stats,
        )
        years_experience_val = None
        if years_exp:
            try:
                years_experience_val = float(years_exp[0])
            except (ValueError, TypeError):
                pass
            provenance.append(years_exp[2])
            field_confidences.append(years_exp[3])

        # Fallback: compute from experience dates if no explicit value.
        if years_experience_val is None and experience:
            computed = self._compute_years_from_experience(experience)
            if computed is not None:
                years_experience_val = computed
                provenance.append(ProvenanceEntry(
                    field="years_experience",
                    source="derived",
                    method="computed_from_experience_dates",
                ))
                field_confidences.append(FieldConfidence(
                    field="years_experience", confidence=0.60,
                ))

        # --- Generate candidate_id ---
        primary_email = emails[0] if emails else None
        company_name = company_result[0] if company_result else None
        candidate_id = CanonicalRecord.generate_candidate_id(
            primary_email=primary_email,
            full_name=full_name[0] if full_name else None,
            company=company_name,
        )

        # --- Assemble record ---
        record = CanonicalRecord(
            candidate_id=candidate_id,
            full_name=full_name[0] if full_name else None,
            emails=emails,
            phones=phones,
            location=location,
            links=links,
            headline=(headline[0] if headline else
                      (title_result[0] if title_result else None)),
            years_experience=years_experience_val,
            skills=skills,
            experience=experience,
            education=education,
            provenance=provenance,
            field_confidences=field_confidences,
        )
        record.compute_overall_confidence()

        # Log null fields.
        for f in ["full_name", "headline", "years_experience"]:
            if getattr(record, f) is None:
                stats.add_null(f)
        if not record.emails:
            stats.add_null("emails")
        if not record.phones:
            stats.add_null("phones")
        if not record.skills:
            stats.add_null("skills")

        return record

    # ------------------------------------------------------------------
    # Scalar merge
    # ------------------------------------------------------------------

    def _merge_scalar(
        self,
        field: str,
        rfvs: list[RawFieldValue],
        normalizer=None,
        stats: MergeStats | None = None,
    ) -> tuple | None:
        """Merge scalar field from multiple sources.

        Returns ``(value, confidence, ProvenanceEntry, FieldConfidence)``
        or ``None`` if no valid value.
        """
        if not rfvs:
            return None

        # Normalize + group by normalized value.
        normalized: list[tuple[str, RawFieldValue]] = []
        for rfv in rfvs:
            val = str(rfv.value).strip() if rfv.value is not None else ""
            if normalizer:
                val = normalizer(val)
            if val:
                normalized.append((val, rfv))

        if not normalized:
            return None

        # Group by normalized value.
        value_groups: dict[str, list[RawFieldValue]] = defaultdict(list)
        for val, rfv in normalized:
            value_groups[val].append(rfv)

        if len(value_groups) == 1:
            # All agree (or single source).
            val = next(iter(value_groups.keys()))
            rfv_list = next(iter(value_groups.values()))
            base_confs = [r.raw_confidence for r in rfv_list]
            if len(rfv_list) > 1:
                confidence = min(1.0, max(base_confs) + AGREEMENT_BONUS)
            else:
                confidence = base_confs[0]
            # Pick the source with highest priority.
            best_rfv = min(rfv_list, key=lambda r: _source_rank(field, r.source))
            return (
                val,
                confidence,
                ProvenanceEntry(field=field, source=best_rfv.source, method=best_rfv.method),
                FieldConfidence(field=field, confidence=confidence),
            )
        else:
            # Conflict — pick highest-priority source, cap confidence.
            all_rfvs_flat = [rfv for _, rfv in normalized]
            best_rfv = min(all_rfvs_flat, key=lambda r: _source_rank(field, r.source))
            # Find the normalized value for the best RFV.
            for val, rfv in normalized:
                if rfv is best_rfv:
                    chosen_val = val
                    break

            if stats:
                stats.add_conflict(
                    field=field,
                    sources=[r.source for _, r in normalized],
                    chosen_source=best_rfv.source,
                )

            return (
                chosen_val,
                CONFLICT_CAP,
                ProvenanceEntry(field=field, source=best_rfv.source, method=best_rfv.method),
                FieldConfidence(field=field, confidence=CONFLICT_CAP, has_conflict=True),
            )

    # ------------------------------------------------------------------
    # List merge (emails, phones — deduplicated)
    # ------------------------------------------------------------------

    def _merge_list_normalized(
        self,
        field: str,
        rfvs: list[RawFieldValue],
        normalizer=None,
        stats: MergeStats | None = None,
        metadata_callback=None,
    ) -> tuple[list[str], list[ProvenanceEntry], FieldConfidence | None]:
        """Merge a list field: normalize, deduplicate, track provenance."""
        if not rfvs:
            return [], [], None

        seen: dict[str, RawFieldValue] = {}  # normalized_val → first RFV
        rejected: list[tuple[str, str, str]] = []  # (raw, reason, source)

        for rfv in rfvs:
            raw = str(rfv.value).strip() if rfv.value is not None else ""
            if not raw:
                continue

            if normalizer:
                val = normalizer(raw)
            else:
                val = raw

            if val is None:
                rejected.append((raw, "normalization_failed", rfv.source))
                continue

            if val not in seen:
                if metadata_callback:
                    metadata_callback(raw, rfv)
                seen[val] = rfv

        # Log rejections.
        if stats:
            for raw_val, reason, source in rejected:
                stats.add_rejection(field=field, value=raw_val, reason=reason, source=source)

        values = list(seen.keys())
        prov = [
            ProvenanceEntry(field=field, source=rfv.source, method=rfv.method)
            for rfv in seen.values()
        ]

        if not values:
            return [], [], None

        # Confidence: agreement bonus if same value from multiple sources.
        all_confs = [r.raw_confidence for r in rfvs if normalizer is None or normalizer(str(r.value).strip()) is not None]
        if len(seen) == 1 and len(all_confs) > 1:
            conf = min(1.0, max(all_confs) + AGREEMENT_BONUS)
        else:
            conf = max(all_confs) if all_confs else 0.5

        return values, prov, FieldConfidence(field=field, confidence=conf)

    # ------------------------------------------------------------------
    # Location merge
    # ------------------------------------------------------------------

    def _merge_location(
        self, by_field: dict, stats: MergeStats | None
    ) -> tuple[Location, list[ProvenanceEntry], list[FieldConfidence]]:
        """Merge location sub-fields: city, region, country."""
        prov: list[ProvenanceEntry] = []
        confs: list[FieldConfidence] = []

        city = self._merge_scalar("location.city", by_field.get("location.city", []), stats=stats)
        region = self._merge_scalar("location.region", by_field.get("location.region", []), stats=stats)
        country_raw = self._merge_scalar(
            "location.country", by_field.get("location.country", []),
            normalizer=normalize_country, stats=stats,
        )

        loc = Location(
            city=city[0] if city else None,
            region=region[0] if region else None,
            country=country_raw[0] if country_raw else None,
        )

        for result in [city, region, country_raw]:
            if result:
                prov.append(result[2])
                confs.append(result[3])

        return loc, prov, confs

    # ------------------------------------------------------------------
    # Links merge
    # ------------------------------------------------------------------

    def _merge_links(
        self, by_field: dict, stats: MergeStats | None
    ) -> tuple[Links, list[ProvenanceEntry]]:
        """Merge link fields."""
        prov: list[ProvenanceEntry] = []

        linkedin = self._merge_scalar("links.linkedin", by_field.get("links.linkedin", []), stats=stats)
        github = self._merge_scalar("links.github", by_field.get("links.github", []), stats=stats)
        portfolio = self._merge_scalar("links.portfolio", by_field.get("links.portfolio", []), stats=stats)

        # Collect 'other' links.
        other_rfvs = by_field.get("links.other", [])
        other_links = list({str(r.value).strip() for r in other_rfvs if r.value})

        links = Links(
            linkedin=linkedin[0] if linkedin else None,
            github=github[0] if github else None,
            portfolio=portfolio[0] if portfolio else None,
            other=other_links,
        )

        for result in [linkedin, github, portfolio]:
            if result:
                prov.append(result[2])

        return links, prov

    # ------------------------------------------------------------------
    # Skills merge
    # ------------------------------------------------------------------

    def _merge_skills(
        self,
        rfvs: list[RawFieldValue],
        stats: MergeStats | None,
    ) -> tuple[list[Skill], list[ProvenanceEntry], FieldConfidence | None]:
        """Merge skills: normalize, deduplicate, compute per-skill confidence."""
        if not rfvs:
            return [], [], None

        # skill_name → {sources, max_confidence, is_verified}
        skill_map: dict[str, dict] = {}
        prov: list[ProvenanceEntry] = []

        for rfv in rfvs:
            raw_skill = str(rfv.value).strip() if rfv.value is not None else ""
            if not raw_skill:
                continue

            canonical, is_verified = normalize_skill(raw_skill)
            if not canonical:
                continue

            if canonical not in skill_map:
                skill_map[canonical] = {
                    "sources": set(),
                    "max_confidence": 0.0,
                    "is_verified": is_verified,
                    "count": 0,
                }

            entry = skill_map[canonical]
            entry["sources"].add(rfv.source)
            entry["max_confidence"] = max(entry["max_confidence"], rfv.raw_confidence)
            entry["count"] += 1
            if is_verified:
                entry["is_verified"] = True

        skills: list[Skill] = []
        for name, info in skill_map.items():
            base = info["max_confidence"]
            # Agreement bonus if seen from multiple sources.
            if len(info["sources"]) > 1:
                conf = min(1.0, base + AGREEMENT_BONUS)
            else:
                conf = base

            # Unverified skills get a penalty.
            if not info["is_verified"]:
                conf = min(conf, 0.5)

            skills.append(Skill(
                name=name,
                confidence=round(conf, 2),
                sources=sorted(info["sources"]),
            ))

            prov.append(ProvenanceEntry(
                field=f"skills.{name}",
                source=", ".join(sorted(info["sources"])),
                method="taxonomy_match" if info["is_verified"] else "passthrough",
            ))

        avg_conf = sum(s.confidence for s in skills) / len(skills) if skills else 0.0
        field_conf = FieldConfidence(field="skills", confidence=round(avg_conf, 2)) if skills else None

        return skills, prov, field_conf

    # ------------------------------------------------------------------
    # Experience merge
    # ------------------------------------------------------------------

    def _merge_experience(
        self, rfvs: list[RawFieldValue]
    ) -> tuple[list[Experience], list[ProvenanceEntry]]:
        """Merge experience entries: normalize dates, deduplicate."""
        if not rfvs:
            return [], []

        experiences: list[Experience] = []
        prov: list[ProvenanceEntry] = []
        seen: set[str] = set()  # Dedup key: (company_lower, title_lower, start)

        for rfv in rfvs:
            val = rfv.value
            if not isinstance(val, dict):
                continue

            company = str(val.get("company", "")).strip()
            title = str(val.get("title", "")).strip()
            if not company and not title:
                continue

            start_raw = val.get("start")
            end_raw = val.get("end")

            start_norm, _ = normalize_date(start_raw)
            end_norm, _ = normalize_date(end_raw)

            dedup_key = f"{company.lower()}|{title.lower()}|{start_norm}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            experiences.append(Experience(
                company=company,
                title=title,
                start=start_norm,
                end=end_norm,
                summary=val.get("summary"),
            ))

            prov.append(ProvenanceEntry(
                field="experience",
                source=rfv.source,
                method=rfv.method,
            ))

        return experiences, prov

    # ------------------------------------------------------------------
    # Education merge
    # ------------------------------------------------------------------

    def _merge_education(
        self, rfvs: list[RawFieldValue]
    ) -> tuple[list[Education], list[ProvenanceEntry]]:
        """Merge education entries: deduplicate by institution+degree."""
        if not rfvs:
            return [], []

        educations: list[Education] = []
        prov: list[ProvenanceEntry] = []
        seen: set[str] = set()

        for rfv in rfvs:
            val = rfv.value
            if not isinstance(val, dict):
                continue

            institution = str(val.get("institution", "")).strip()
            if not institution:
                continue

            degree = val.get("degree")
            field = val.get("field")
            end_year = val.get("end_year")

            dedup_key = f"{institution.lower()}|{str(degree).lower()}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            educations.append(Education(
                institution=institution,
                degree=degree,
                field=field,
                end_year=int(end_year) if end_year is not None else None,
            ))

            prov.append(ProvenanceEntry(
                field="education",
                source=rfv.source,
                method=rfv.method,
            ))

        return educations, prov

    # ------------------------------------------------------------------
    # years_experience computation from experience dates
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_years_from_experience(
        experience: list[Experience],
    ) -> float | None:
        """Compute total years of experience from experience date ranges.

        Sums non-overlapping spans in months.  "Present"/null end dates resolve
        to the current month.  Returns ``None`` if no usable dates exist.
        """
        intervals: list[tuple[int, int]] = []  # (start_month_idx, end_month_idx)
        today = date.today()
        current_month_idx = today.year * 12 + today.month

        for exp in experience:
            if not exp.start:
                continue

            try:
                parts = exp.start.split("-")
                start_y, start_m = int(parts[0]), int(parts[1])
                start_idx = start_y * 12 + start_m
            except (ValueError, IndexError):
                continue

            if exp.end:
                try:
                    parts = exp.end.split("-")
                    end_y, end_m = int(parts[0]), int(parts[1])
                    end_idx = end_y * 12 + end_m
                except (ValueError, IndexError):
                    end_idx = current_month_idx
            else:
                end_idx = current_month_idx

            if end_idx >= start_idx:
                intervals.append((start_idx, end_idx))

        if not intervals:
            return None

        # Merge overlapping intervals.
        intervals.sort()
        merged: list[tuple[int, int]] = [intervals[0]]
        for start, end in intervals[1:]:
            if start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        total_months = sum(end - start for start, end in merged)
        return round(total_months / 12.0, 1)
