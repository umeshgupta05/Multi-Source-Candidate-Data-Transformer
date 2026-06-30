"""Pipeline — orchestrates the full 8-stage transformation pipeline.

detect → extract → normalize → resolve → merge → score → project → validate → emit

This module wires together all the components and provides a single entry
point for the web UI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from candidate_transformer.models.config import ProjectionConfig
from candidate_transformer.models.raw import RawFieldValue
from candidate_transformer.models.canonical import CanonicalRecord
from candidate_transformer.extractors.csv_extractor import CSVExtractor
from candidate_transformer.extractors.ats_extractor import ATSExtractor
from candidate_transformer.extractors.github_extractor import GitHubExtractor
from candidate_transformer.extractors.resume_extractor import ResumeExtractor
from candidate_transformer.extractors.resume_extractor_llm import ResumeLLMExtractor

from candidate_transformer.resolver import EntityResolver
from candidate_transformer.merger import Merger, MergeStats
from candidate_transformer.projector import Projector, ProjectionError
from candidate_transformer.validator import Validator

logger = logging.getLogger(__name__)


class PipelineResult:
    """Result of a pipeline run."""

    def __init__(self):
        self.candidates: list[dict[str, Any]] = []
        self.canonical_records: list[CanonicalRecord] = []
        self.validation_errors: list[str] = []
        self.stats: RunSummary = RunSummary()


class RunSummary:
    """Aggregated run statistics for CLI output."""

    def __init__(self):
        self.sources_loaded: list[str] = []
        self.sources_failed: list[str] = []
        self.total_rfvs: int = 0
        self.candidates_processed: int = 0
        self.conflicts: list[dict] = []
        self.rejections: list[dict] = []
        self.null_fields: list[str] = []
        self.validation_errors: list[str] = []

    def to_dict(self) -> dict:
        return {
            "sources_loaded": self.sources_loaded,
            "sources_failed": self.sources_failed,
            "total_raw_field_values": self.total_rfvs,
            "candidates_processed": self.candidates_processed,
            "conflicts_found": len(self.conflicts),
            "conflict_details": self.conflicts,
            "rejections": len(self.rejections),
            "rejection_details": self.rejections,
            "fields_nulled": self.null_fields,
            "validation_errors": self.validation_errors,
        }

    def print_summary(self) -> str:
        """Format a human-readable run summary."""
        lines = [
            "",
            "=" * 60,
            "  PIPELINE RUN SUMMARY",
            "=" * 60,
            f"  Sources loaded:        {', '.join(self.sources_loaded) or 'none'}",
            f"  Sources failed:        {', '.join(self.sources_failed) or 'none'}",
            f"  Raw field values:      {self.total_rfvs}",
            f"  Candidates processed:  {self.candidates_processed}",
            f"  Conflicts found:       {len(self.conflicts)}",
            f"  Values rejected:       {len(self.rejections)}",
            f"  Fields left null:      {len(self.null_fields)}",
            f"  Validation errors:     {len(self.validation_errors)}",
        ]

        if self.conflicts:
            lines.append("")
            lines.append("  CONFLICTS:")
            for c in self.conflicts:
                lines.append(
                    f"    • {c['field']}: sources={c['sources']} → chose {c['chosen']}"
                )

        if self.rejections:
            lines.append("")
            lines.append("  REJECTIONS (dropped values):")
            for r in self.rejections:
                lines.append(
                    f"    • {r['field']}: '{r['value']}' from {r['source']} ({r['reason']})"
                )

        if self.validation_errors:
            lines.append("")
            lines.append("  VALIDATION ERRORS:")
            for e in self.validation_errors:
                lines.append(f"    • {e}")

        lines.append("=" * 60)
        return "\n".join(lines)


def run_pipeline(
    csv_path: str | None = None,
    ats_path: str | None = None,
    github_urls_path: str | None = None,
    resumes_path: str | None = None,
    config_path: str | None = None,
    output_path: str | None = None,
    resume_extraction_mode: Literal["regex", "llm", "both"] = "regex",
    github_readme_llm: bool | None = None,
) -> PipelineResult:
    """Execute the full pipeline end-to-end.

    Args:
        csv_path: Path to recruiter CSV file.
        ats_path: Path to ATS JSON file.
        github_urls_path: Path to text file with GitHub usernames.
        resumes_path: Path to resume file or directory.
        config_path: Path to projection config JSON.
        output_path: Path to write output JSON.
        resume_extraction_mode: "regex" for the deterministic extractor,
            "llm" for the optional Qwen extractor, or "both" to compare them.
        github_readme_llm: If True, opt into Qwen parsing for GitHub profile
            README text. If None, GitHubExtractor uses QWEN_GITHUB_README_LLM,
            which defaults to false.

    Returns:
        PipelineResult with projected candidates, stats, and errors.
    """
    result = PipelineResult()
    summary = result.stats

    # ------------------------------------------------------------------
    # 1-2. Detect + Extract
    # ------------------------------------------------------------------
    all_rfvs: list[RawFieldValue] = []

    extractors = [
        ("recruiter_csv", csv_path, CSVExtractor()),
        ("ats_json", ats_path, ATSExtractor()),
        ("github_api", github_urls_path, GitHubExtractor(readme_llm_enabled=github_readme_llm)),
    ]
    extractors.extend(_resume_extractors_for_mode(resumes_path, resume_extraction_mode))

    for source_name, path, extractor in extractors:
        if not path:
            continue
        try:
            rfvs = extractor.extract(path)
            if rfvs:
                all_rfvs.extend(rfvs)
                summary.sources_loaded.append(source_name)
            else:
                detail = getattr(extractor, "last_error", None)
                summary.sources_failed.append(
                    f"{source_name} ({detail})" if detail else f"{source_name} (empty/not found)"
                )
        except Exception:
            logger.exception("Extractor failed for %s", source_name)
            summary.sources_failed.append(f"{source_name} (error)")

    summary.total_rfvs = len(all_rfvs)
    logger.info("Extraction complete: %d raw field values from %d sources.",
                len(all_rfvs), len(summary.sources_loaded))

    if not all_rfvs:
        logger.warning("No data extracted from any source — nothing to process.")
        return result

    # ------------------------------------------------------------------
    # 3. Normalize (happens inside merger per-field)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # 4. Resolve (entity matching across sources)
    # ------------------------------------------------------------------
    resolver = EntityResolver()
    clusters = resolver.resolve(all_rfvs)

    # ------------------------------------------------------------------
    # 5-6. Merge + Score (per cluster → CanonicalRecord)
    # ------------------------------------------------------------------
    merger = Merger()
    canonical_records: list[CanonicalRecord] = []

    for cluster_id, cluster_rfvs in clusters.items():
        merge_stats = MergeStats()
        record = merger.merge(cluster_rfvs, merge_stats)
        canonical_records.append(record)

        # Aggregate stats.
        summary.conflicts.extend(merge_stats.conflicts)
        summary.rejections.extend(merge_stats.rejections)
        summary.null_fields.extend(merge_stats.null_fields)

    result.canonical_records = canonical_records
    summary.candidates_processed = len(canonical_records)

    logger.info("Merged %d candidates from %d clusters.",
                len(canonical_records), len(clusters))

    # ------------------------------------------------------------------
    # 7. Project (config-driven)
    # ------------------------------------------------------------------
    config = _load_config(config_path)
    projector = Projector()
    validator = Validator()

    projected: list[dict] = []
    for record in canonical_records:
        try:
            out = projector.project(record, config)

            # 8. Validate.
            errors = validator.validate(out, config)
            if errors:
                for err in errors:
                    summary.validation_errors.append(str(err))
                    result.validation_errors.append(str(err))

            projected.append(out)
        except ProjectionError as exc:
            logger.warning("Projection error for candidate %s: %s",
                           record.candidate_id, exc)
            summary.validation_errors.append(str(exc))
            result.validation_errors.append(str(exc))
            # Still include what we have — partial is better than nothing.
            projected.append({"candidate_id": record.candidate_id, "error": str(exc)})

    result.candidates = projected

    # ------------------------------------------------------------------
    # 9. Emit
    # ------------------------------------------------------------------
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(projected, fh, indent=2, default=str)
        logger.info("Output written to %s", out_path)

    return result


def _load_config(config_path: str | None) -> ProjectionConfig:
    """Load a ProjectionConfig from JSON, falling back to configs/default.json."""
    if config_path:
        path = Path(config_path)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return ProjectionConfig(**data)
        else:
            logger.warning("Config file not found: %s — using default.", config_path)

    project_root = Path(__file__).resolve().parents[2]
    default_config_path = project_root / "configs" / "default.json"
    data = json.loads(default_config_path.read_text(encoding="utf-8"))
    return ProjectionConfig(**data)


def _resume_extractors_for_mode(
    resumes_path: str | None,
    mode: Literal["regex", "llm", "both"],
) -> list[tuple[str, str | None, object]]:
    """Build resume extractors for the requested extraction mode."""
    if mode == "regex":
        return [("resume_pdf", resumes_path, ResumeExtractor())]
    if mode == "llm":
        return [("resume_llm", resumes_path, ResumeLLMExtractor())]
    if mode == "both":
        return [
            ("resume_pdf", resumes_path, ResumeExtractor()),
            ("resume_llm", resumes_path, ResumeLLMExtractor()),
        ]
    raise ValueError(f"Unsupported resume_extraction_mode: {mode}")
