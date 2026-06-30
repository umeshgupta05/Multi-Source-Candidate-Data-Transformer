"""Unit tests for extractors."""

import json
import csv
import tempfile
from pathlib import Path

import pytest

from candidate_transformer.extractors.csv_extractor import CSVExtractor
from candidate_transformer.extractors.ats_extractor import ATSExtractor
from candidate_transformer.extractors.github_extractor import GitHubExtractor
from candidate_transformer.extractors.resume_extractor import ResumeExtractor


# ======================================================================
# CSV Extractor
# ======================================================================

class TestCSVExtractor:
    def test_basic_extraction(self, tmp_path):
        """Test basic CSV extraction with valid data."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "name,email,phone,current_company,title\n"
            "Jane Doe,jane@example.com,+15550101,Acme,Engineer\n"
        )

        ext = CSVExtractor()
        rfvs = ext.extract(csv_file)

        assert len(rfvs) == 5  # 5 fields
        fields = {r.field for r in rfvs}
        assert "full_name" in fields
        assert "emails" in fields
        assert "phones" in fields
        assert "current_company" in fields
        assert "title" in fields

    def test_missing_file_returns_empty(self, tmp_path):
        """Test graceful handling of missing file."""
        ext = CSVExtractor()
        rfvs = ext.extract(tmp_path / "nonexistent.csv")
        assert rfvs == []

    def test_empty_file_returns_empty(self, tmp_path):
        """Test graceful handling of empty file."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")

        ext = CSVExtractor()
        rfvs = ext.extract(csv_file)
        assert rfvs == []

    def test_missing_columns(self, tmp_path):
        """Test CSV with missing expected columns (partial extraction)."""
        csv_file = tmp_path / "partial.csv"
        csv_file.write_text(
            "name,email\n"
            "Jane Doe,jane@example.com\n"
        )

        ext = CSVExtractor()
        rfvs = ext.extract(csv_file)

        # Should still extract what it can.
        assert len(rfvs) == 2
        fields = {r.field for r in rfvs}
        assert "full_name" in fields
        assert "emails" in fields

    def test_empty_cells_skipped(self, tmp_path):
        """Test that empty cell values are skipped."""
        csv_file = tmp_path / "empty_cells.csv"
        csv_file.write_text(
            "name,email,phone,current_company,title\n"
            "Jane Doe,jane@example.com,,,\n"
        )

        ext = CSVExtractor()
        rfvs = ext.extract(csv_file)

        fields = {r.field for r in rfvs}
        assert "full_name" in fields
        assert "emails" in fields
        assert "phones" not in fields  # Empty phone should be skipped.

    def test_row_without_name_or_email_skipped(self, tmp_path):
        """Test that rows with no name AND no email are skipped entirely."""
        csv_file = tmp_path / "no_identity.csv"
        csv_file.write_text(
            "name,email,phone,current_company,title\n"
            ",,+15550101,Acme,Engineer\n"
        )

        ext = CSVExtractor()
        rfvs = ext.extract(csv_file)
        assert rfvs == []

    def test_confidence_is_095(self, tmp_path):
        """All CSV fields should have base confidence 0.95."""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "name,email,phone,current_company,title\n"
            "Jane,jane@ex.com,+15550101,Acme,Eng\n"
        )

        ext = CSVExtractor()
        rfvs = ext.extract(csv_file)
        assert all(r.raw_confidence == 0.95 for r in rfvs)

    def test_alias_columns_and_multivalue_cells(self, tmp_path):
        """Recruiter exports often rename columns and pack skills into one cell."""
        csv_file = tmp_path / "messy.csv"
        csv_file.write_text(
            "Candidate Name,Email Address,Mobile,Company,Position,Tech Stack,LinkedIn URL\n"
            "Jane Doe,jane@example.com,+15550101,Acme,Engineer,\"Python; React | AWS\",https://linkedin.com/in/jane\n"
        )

        rfvs = CSVExtractor().extract(csv_file)
        values = {(r.field, r.value) for r in rfvs}

        assert ("full_name", "Jane Doe") in values
        assert ("emails", "jane@example.com") in values
        assert ("phones", "+15550101") in values
        assert ("current_company", "Acme") in values
        assert ("title", "Engineer") in values
        assert ("links.linkedin", "https://linkedin.com/in/jane") in values
        assert ("skills", "Python") in values
        assert ("skills", "React") in values
        assert ("skills", "AWS") in values

    def test_freeform_location_column_is_split(self, tmp_path):
        csv_file = tmp_path / "location.csv"
        csv_file.write_text(
            "name,email,location\n"
            "Jane Doe,jane@example.com,\"San Francisco, CA\"\n"
        )

        rfvs = CSVExtractor().extract(csv_file)
        values = {(r.field, r.value) for r in rfvs}

        assert ("location.city", "San Francisco") in values
        assert ("location.region", "CA") in values
        assert ("location.country", "US") in values


# ======================================================================
# ATS Extractor
# ======================================================================

class TestATSExtractor:
    def test_basic_extraction(self, tmp_path):
        """Test basic ATS JSON extraction."""
        ats_file = tmp_path / "ats.json"
        data = {
            "applicants": [
                {
                    "applicant_name": "Jane Doe",
                    "contact_email": "jane@example.com",
                    "contact_phone": "+15550101",
                    "current_employer": "Acme",
                    "job_title": "Engineer",
                    "skills_list": ["Python", "Go"],
                }
            ]
        }
        ats_file.write_text(json.dumps(data))

        ext = ATSExtractor()
        rfvs = ext.extract(ats_file)

        fields = {r.field for r in rfvs}
        assert "full_name" in fields
        assert "emails" in fields
        assert "skills" in fields

    def test_missing_fields_soft_fail(self, tmp_path):
        """Test per-field soft failure — missing field doesn't skip record."""
        ats_file = tmp_path / "ats.json"
        data = {
            "applicants": [
                {
                    "applicant_name": "Jane Doe",
                    "contact_email": "jane@example.com",
                    # No phone, no skills, no employer — should still extract name+email.
                }
            ]
        }
        ats_file.write_text(json.dumps(data))

        ext = ATSExtractor()
        rfvs = ext.extract(ats_file)

        assert len(rfvs) >= 2
        fields = {r.field for r in rfvs}
        assert "full_name" in fields
        assert "emails" in fields

    def test_malformed_json(self, tmp_path):
        """Test graceful handling of malformed JSON."""
        ats_file = tmp_path / "bad.json"
        ats_file.write_text("{not valid json")

        ext = ATSExtractor()
        rfvs = ext.extract(ats_file)
        assert rfvs == []

    def test_missing_file(self, tmp_path):
        """Test graceful handling of missing file."""
        ext = ATSExtractor()
        rfvs = ext.extract(tmp_path / "nonexistent.json")
        assert rfvs == []

    def test_education_extraction(self, tmp_path):
        """Test education entry extraction."""
        ats_file = tmp_path / "ats.json"
        data = {
            "applicants": [
                {
                    "applicant_name": "Jane Doe",
                    "contact_email": "jane@example.com",
                    "education": [
                        {
                            "school": "MIT",
                            "degree_type": "M.S.",
                            "major": "CS",
                            "graduation_year": 2020,
                        }
                    ],
                }
            ]
        }
        ats_file.write_text(json.dumps(data))

        ext = ATSExtractor()
        rfvs = ext.extract(ats_file)

        edu_rfvs = [r for r in rfvs if r.field == "education"]
        assert len(edu_rfvs) == 1
        assert edu_rfvs[0].value["institution"] == "MIT"

    def test_work_history_extraction(self, tmp_path):
        """Test work history → experience extraction."""
        ats_file = tmp_path / "ats.json"
        data = {
            "applicants": [
                {
                    "applicant_name": "Jane",
                    "contact_email": "j@ex.com",
                    "work_history": [
                        {
                            "employer": "Acme",
                            "role": "Engineer",
                            "start_date": "2020-03",
                            "end_date": None,
                        }
                    ],
                }
            ]
        }
        ats_file.write_text(json.dumps(data))

        ext = ATSExtractor()
        rfvs = ext.extract(ats_file)

        exp_rfvs = [r for r in rfvs if r.field == "experience"]
        assert len(exp_rfvs) == 1
        assert exp_rfvs[0].value["company"] == "Acme"

    def test_nested_and_alias_ats_schema(self, tmp_path):
        """ATS exports may be nested or use vendor-specific aliases."""
        ats_file = tmp_path / "nested_ats.json"
        data = {
            "candidates": [
                {
                    "profile": {"name": "Jane Doe", "email": "jane@example.com"},
                    "contact": {"phones": ["+15550101"]},
                    "location": {"city": "Austin", "state": "TX", "country": "US"},
                    "role": "Backend Engineer",
                    "company": "Acme",
                    "skills": "Python, FastAPI; PostgreSQL",
                    "educations": {
                        "institution": "UT Austin",
                        "degree": "B.S.",
                        "field": "Computer Science",
                        "end_year": 2020,
                    },
                    "experience": {
                        "company": "Acme",
                        "title": "Engineer",
                        "start": "2021-01",
                        "end": None,
                        "description": "Built APIs.",
                    },
                }
            ]
        }
        ats_file.write_text(json.dumps(data))

        rfvs = ATSExtractor().extract(ats_file)
        values = {(r.field, r.value) for r in rfvs if isinstance(r.value, str)}

        assert ("full_name", "Jane Doe") in values
        assert ("emails", "jane@example.com") in values
        assert ("phones", "+15550101") in values
        assert ("location.city", "Austin") in values
        assert ("skills", "Python") in values
        assert ("skills", "FastAPI") in values
        assert ("skills", "PostgreSQL") in values
        assert any(r.field == "education" and r.value["institution"] == "UT Austin" for r in rfvs)
        assert any(r.field == "experience" and r.value["summary"] == "Built APIs." for r in rfvs)

    def test_string_location_field_is_split(self, tmp_path):
        ats_file = tmp_path / "ats_location.json"
        data = {
            "applicants": [
                {
                    "applicant_name": "Isha Rao",
                    "contact_email": "isha@example.com",
                    "location": "Bengaluru, Karnataka, India",
                }
            ]
        }
        ats_file.write_text(json.dumps(data))

        rfvs = ATSExtractor().extract(ats_file)
        values = {(r.field, r.value) for r in rfvs if isinstance(r.value, str)}

        assert ("location.city", "Bengaluru") in values
        assert ("location.region", "Karnataka") in values
        assert ("location.country", "IN") in values


# ======================================================================
# GitHub README Extractor
# ======================================================================

class TestGitHubReadmeExtraction:
    def test_normalizes_github_url_to_username(self):
        assert GitHubExtractor._normalize_username("https://github.com/octocat/") == "octocat"
        assert GitHubExtractor._normalize_username("github.com/octocat?tab=repositories") == "octocat"
        assert GitHubExtractor._normalize_username("\ufeffsindresorhus") == "sindresorhus"

    def test_profile_readme_regex_extracts_skills_links_and_headline(self, monkeypatch):
        monkeypatch.setenv("QWEN_GITHUB_README_LLM", "false")
        readme = """
        # Jane Doe
        Full-stack engineer building cloud data products.

        Based in: London, United Kingdom
        Portfolio: https://janedoe.dev
        LinkedIn: https://linkedin.com/in/janedoe
        Stack: Python, React, TypeScript, AWS, Docker, PostgreSQL
        """

        ext = GitHubExtractor()
        rfvs = ext._extract_readme_regex(readme, "jane", "janedoe")

        values = {(r.field, r.value) for r in rfvs}
        assert ("links.portfolio", "https://janedoe.dev") in values
        assert ("links.linkedin", "https://linkedin.com/in/janedoe") in values
        assert ("headline", "Full-stack engineer building cloud data products.") in values
        assert ("location.city", "London") in values
        assert ("location.country", "GB") in values
        assert ("skills", "Python") in values
        assert ("skills", "React") in values
        assert {r.source for r in rfvs} == {"github_readme_regex"}

    def test_github_api_location_is_split(self, monkeypatch):
        monkeypatch.setenv("QWEN_GITHUB_README_LLM", "false")
        ext = GitHubExtractor(readme_llm_enabled=False)

        def fake_api_get(endpoint):
            if endpoint == "/users/janedoe":
                return {
                    "login": "janedoe",
                    "name": "Jane Doe",
                    "email": None,
                    "bio": None,
                    "location": "San Francisco, CA",
                    "blog": "",
                    "html_url": "https://github.com/janedoe",
                    "company": "",
                }
            if endpoint.startswith("/users/janedoe/repos"):
                return []
            return None

        monkeypatch.setattr(ext, "_api_get", fake_api_get)
        monkeypatch.setattr(ext, "_fetch_profile_readme", lambda username: None)

        rfvs = ext._extract_user("janedoe")
        values = {(r.field, r.value) for r in rfvs}

        assert ("location.city", "San Francisco") in values
        assert ("location.region", "CA") in values
        assert ("location.country", "US") in values


# ======================================================================
# Resume Extractor
# ======================================================================

class TestResumeExtractor:
    def test_skills_section_stops_at_professional_experience(self):
        text = """
        Jane Doe
        jane@example.com

        Technical Skills
        Programming Languages: Python, JavaScript
        Cloud & Platforms: AWS, Docker

        Professional Experience
        Acme - Engineer Jan 2022 - Present
        Developed APIs and reduced latency by 20%.

        Technical Projects
        Search platform with React and FastAPI.
        """

        ext = ResumeExtractor()
        rfvs = ext._parse_text(text, "resume.pdf")
        skills = [r.value for r in rfvs if r.field == "skills"]

        assert "Python" in skills
        assert "JavaScript" in skills
        assert "AWS" in skills
        assert "Docker" in skills
        assert "Professional Experience" not in skills
        assert not any("Developed APIs" in skill for skill in skills)

    def test_repairs_common_pdf_spacing_in_experience_summary(self):
        raw = (
            "Engineered across-plat form mobile applicationusing React Nativewith Expo "
            "bymigratinga React-based webchatbot, enabling seamless AI-driven healthcare "
            "interactions for 500+ users during testing. Collaboratedindebugging "
            "andfeatureenhancements, improvingappstability andreducing crash occurrencesby20%."
        )

        repaired = ResumeExtractor._repair_spacing(raw)

        assert "across-platform mobile application using React Native with Expo" in repaired
        assert "by migrating a React-based web chatbot" in repaired
        assert "Collaborated in debugging and feature enhancements" in repaired
        assert "improving app stability and reducing crash occurrences by 20%" in repaired

    def test_extracts_location_from_contact_header(self):
        text = """
        Jane Doe
        jane@example.com | +1-202-555-0147 | San Francisco, CA
        github.com/janedoe | linkedin.com/in/janedoe

        Summary
        Backend engineer.
        """

        rfvs = ResumeExtractor()._parse_text(text, "resume.pdf")
        values = {(r.field, r.value) for r in rfvs}

        assert ("location.city", "San Francisco") in values
        assert ("location.region", "CA") in values
        assert ("location.country", "US") in values
