"""Tests for the optional Qwen resume extractor."""

import json
import os

from candidate_transformer.extractors.resume_extractor_llm import ResumeLLMExtractor, _load_env_file
from candidate_transformer.models.raw import RawFieldValue
from candidate_transformer.pipeline import _resume_extractors_for_mode


def test_llm_resume_extractor_parses_json_to_rfvs(tmp_path, monkeypatch):
    resume = tmp_path / "resume.pdf"
    resume.write_text("placeholder")

    payload = {
        "full_name": "jane doe",
        "emails": ["JANE@EXAMPLE.COM", "bad-email"],
        "phones": ["+1 202 456 1111"],
        "headline": "Senior engineer",
        "skills": ["python", "k8s"],
        "experience": [
            {
                "company": "Acme",
                "title": "Engineer",
                "start": "Jan 2020",
                "end": "Present",
                "summary": "Built systems.",
            }
        ],
        "education": [
            {
                "institution": "MIT",
                "degree": "M.S.",
                "field": "CS",
                "end_year": "2021",
            }
        ],
    }

    extractor = ResumeLLMExtractor()
    monkeypatch.setenv("QWEN_PROVIDER", "openai")
    monkeypatch.setattr(extractor, "_read_text", lambda path: "resume text")
    monkeypatch.setattr(extractor, "_call_qwen", lambda text: f"```json\n{json.dumps(payload)}\n```")

    rfvs = extractor.extract(resume)

    assert rfvs
    assert {r.source for r in rfvs} == {"resume_llm"}
    assert {r.method for r in rfvs} == {"llm_extraction_qwen"}
    assert all(r.raw_confidence == 0.55 for r in rfvs)
    scalar_values = {(r.field, r.value) for r in rfvs if isinstance(r.value, str)}
    assert ("emails", "jane@example.com") in scalar_values
    assert ("phones", "+12024561111") in scalar_values
    assert ("skills", "Python") in scalar_values
    assert ("skills", "Kubernetes") in scalar_values

    exp = next(r.value for r in rfvs if r.field == "experience")
    assert exp["start"] == "2020-01"
    assert exp["end"] is None


def test_llm_resume_extractor_malformed_json_returns_empty(tmp_path, monkeypatch):
    resume = tmp_path / "resume.pdf"
    resume.write_text("placeholder")

    extractor = ResumeLLMExtractor()
    monkeypatch.setenv("QWEN_PROVIDER", "openai")
    monkeypatch.setattr(extractor, "_read_text", lambda path: "resume text")
    monkeypatch.setattr(extractor, "_call_qwen", lambda text: "not json")

    assert extractor.extract(resume) == []
    assert extractor.last_error


def test_env_loader_sets_missing_values_without_overriding(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "HF_TOKEN=from-file\n"
        "QWEN_PROVIDER=hf_vlm\n"
        "QWEN_TIMEOUT_SECONDS='45'\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setenv("QWEN_PROVIDER", "already-set")
    monkeypatch.delenv("QWEN_TIMEOUT_SECONDS", raising=False)

    _load_env_file(env_file)

    assert os.environ["HF_TOKEN"] == "from-file"
    assert os.environ["QWEN_PROVIDER"] == "already-set"
    assert os.environ["QWEN_TIMEOUT_SECONDS"] == "45"


def test_both_resume_mode_can_emit_regex_and_llm_sources(tmp_path, monkeypatch):
    resume = tmp_path / "resume.pdf"
    resume.write_text("placeholder")

    class FakeRegexExtractor:
        def extract(self, path):
            return [
                RawFieldValue(
                    candidate_key="jane@example.com",
                    field="emails",
                    value="jane@example.com",
                    source="resume_pdf",
                    method="regex_extract",
                    raw_confidence=0.70,
                )
            ]

    class FakeLLMExtractor:
        def extract(self, path):
            return [
                RawFieldValue(
                    candidate_key="jane@example.com",
                    field="emails",
                    value="jane@example.com",
                    source="resume_llm",
                    method="llm_extraction_qwen",
                    raw_confidence=0.55,
                )
            ]

    monkeypatch.setattr("candidate_transformer.pipeline.ResumeExtractor", FakeRegexExtractor)
    monkeypatch.setattr("candidate_transformer.pipeline.ResumeLLMExtractor", FakeLLMExtractor)

    extractors = _resume_extractors_for_mode(str(resume), "both")
    rfvs = []
    for _, path, extractor in extractors:
        rfvs.extend(extractor.extract(path))

    assert {r.source for r in rfvs} == {"resume_pdf", "resume_llm"}
    assert {r.candidate_key for r in rfvs} == {"jane@example.com"}
