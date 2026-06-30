"""Edge-case tests — explicitly tests the 6 documented edge cases."""

import json

import pytest

from candidate_transformer.extractors.csv_extractor import CSVExtractor
from candidate_transformer.extractors.ats_extractor import ATSExtractor
from candidate_transformer.models.config import ProjectionConfig
from candidate_transformer.models.raw import RawFieldValue
from candidate_transformer.merger import Merger, MergeStats
from candidate_transformer.projector import Projector, ProjectionError
from candidate_transformer.validator import Validator


class TestEdgeCases:
    """Test the 6 documented edge cases."""

    # 1. Missing/empty source file — skip gracefully, don't crash.
    def test_missing_source_file(self, tmp_path):
        ext = CSVExtractor()
        rfvs = ext.extract(tmp_path / "does_not_exist.csv")
        assert rfvs == []

    def test_empty_source_file(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("")
        ext = CSVExtractor()
        rfvs = ext.extract(empty)
        assert rfvs == []

    # 2. Malformed CSV row — skip row, log warning, continue.
    def test_malformed_csv_row(self, tmp_path):
        csv_file = tmp_path / "malformed.csv"
        csv_file.write_text(
            "name,email,phone,current_company,title\n"
            "Jane Doe,jane@ex.com,+15550101,Acme,Engineer\n"
            ",,,,\n"  # Empty row → skipped (no name or email)
            "Bob Smith,bob@ex.com,+15550202,TechCo,Dev\n"
        )
        ext = CSVExtractor()
        rfvs = ext.extract(csv_file)

        # Should have data for Jane and Bob, but not the empty row.
        candidate_keys = {r.candidate_key for r in rfvs}
        assert len(candidate_keys) == 2

    # 3. ATS JSON with unexpected field names — soft-fail per field.
    def test_ats_unexpected_fields(self, tmp_path):
        ats_file = tmp_path / "weird_ats.json"
        data = {
            "applicants": [
                {
                    "applicant_name": "Jane Doe",
                    "contact_email": "jane@ex.com",
                    # These fields are NOT in our mapping — should be ignored.
                    "custom_field_xyz": "some value",
                    "internal_rating": 4.5,
                }
            ]
        }
        ats_file.write_text(json.dumps(data))

        ext = ATSExtractor()
        rfvs = ext.extract(ats_file)

        # Should still get name and email despite unknown fields.
        fields = {r.field for r in rfvs}
        assert "full_name" in fields
        assert "emails" in fields

    # 4. Conflicting emails across sources — resolved via priority + flag.
    def test_conflicting_data_resolved(self):
        rfvs = [
            RawFieldValue(
                candidate_key="jane@ex.com",
                field="full_name",
                value="Jane Doe",
                source="recruiter_csv",
                method="direct_copy",
                raw_confidence=0.95,
            ),
            RawFieldValue(
                candidate_key="jane@ex.com",
                field="full_name",
                value="Jane A. Doe",
                source="ats_json",
                method="direct_copy",
                raw_confidence=0.95,
            ),
            RawFieldValue(
                candidate_key="jane@ex.com",
                field="emails",
                value="jane@ex.com",
                source="recruiter_csv",
                method="direct_copy",
                raw_confidence=0.95,
            ),
        ]
        merger = Merger()
        stats = MergeStats()
        record = merger.merge(rfvs, stats)

        # recruiter_csv has higher priority → "Jane Doe" chosen.
        assert record.full_name == "Jane Doe"
        # Conflict should be logged.
        assert len(stats.conflicts) > 0
        # Confidence should be capped at 0.6.
        name_conf = next(
            (fc for fc in record.field_confidences if fc.field == "full_name"),
            None,
        )
        assert name_conf is not None
        assert name_conf.confidence == 0.6
        assert name_conf.has_conflict

    # 5. GitHub 404 — handled by the extractor returning empty.
    #    (Tested via mock in test_extractors or integration test with fake URL.)

    # 6. Unparseable phone — dropped from phones[], logged as rejection.
    def test_unparseable_phone_dropped(self):
        rfvs = [
            RawFieldValue(
                candidate_key="jane@ex.com",
                field="emails",
                value="jane@ex.com",
                source="recruiter_csv",
                method="direct_copy",
                raw_confidence=0.95,
            ),
            RawFieldValue(
                candidate_key="jane@ex.com",
                field="phones",
                value="not-a-phone-number",
                source="recruiter_csv",
                method="direct_copy",
                raw_confidence=0.95,
            ),
        ]
        merger = Merger()
        stats = MergeStats()
        record = merger.merge(rfvs, stats)

        # Bad phone should be dropped.
        assert len(record.phones) == 0
        # Rejection should be logged in stats (CLI summary), NOT provenance.
        assert len(stats.rejections) > 0
        assert any(r["field"] == "phones" for r in stats.rejections)

    # Bonus: Dynamic validator catches type mismatches.
    def test_validator_catches_wrong_type(self):
        config = ProjectionConfig(
            fields=[
                {"path": "name", "from": "full_name", "type": "string"},
            ],
            include_confidence=False,
            on_missing="null",
        )
        # Feed it a projected output with wrong type.
        bad_output = {"name": 42}
        validator = Validator()
        errors = validator.validate(bad_output, config)
        assert len(errors) > 0
        assert "string" in errors[0].message.lower()

    # Bonus: Validator derives schema from config — not hardcoded.
    def test_validator_derives_schema_from_config(self):
        config = ProjectionConfig(
            fields=[
                {"path": "custom_field", "from": "full_name", "type": "number"},
            ],
            include_confidence=False,
            on_missing="null",
        )
        # String value but expected number → validation error.
        output = {"custom_field": "not a number"}
        validator = Validator()
        errors = validator.validate(output, config)
        assert len(errors) > 0
