"""Unit tests for all normalizers."""

import pytest

from candidate_transformer.normalizers.phone import normalize_phone, normalize_phone_with_candidates
from candidate_transformer.normalizers.date import normalize_date
from candidate_transformer.normalizers.country import normalize_country
from candidate_transformer.normalizers.skills import normalize_skill
from candidate_transformer.normalizers.email import normalize_email
from candidate_transformer.normalizers.name import normalize_name


# ======================================================================
# Phone normalizer
# ======================================================================

class TestNormalizePhone:
    def test_us_phone_e164(self):
        # Use a valid US number (not 555-xxx which are fictitious/rejected).
        assert normalize_phone("+1-202-456-1111") == "+12024561111"

    def test_us_phone_parentheses(self):
        result = normalize_phone("(212) 555-1234")
        assert result == "+12125551234"

    def test_us_phone_dots(self):
        result = normalize_phone("+1.650.253.0000")
        assert result == "+16502530000"

    def test_uk_phone(self):
        result = normalize_phone("+44 7911 123456")
        assert result == "+447911123456"

    def test_invalid_phone_returns_none(self):
        assert normalize_phone("not-a-phone") is None

    def test_empty_phone_returns_none(self):
        assert normalize_phone("") is None
        assert normalize_phone(None) is None

    def test_short_number_invalid(self):
        assert normalize_phone("123") is None

    def test_candidate_region_uk_local_number(self):
        value, region = normalize_phone_with_candidates(
            "07911 123456",
            candidate_regions=["GB"],
            fallback_region="US",
        )
        assert value == "+447911123456"
        assert region == "GB"

    def test_wrong_candidate_region_does_not_force_invalid_guess(self):
        value, region = normalize_phone_with_candidates(
            "07911 123456",
            candidate_regions=["IN"],
            fallback_region="US",
        )
        assert (value, region) == (None, None)

    def test_international_number_ignores_candidate_regions(self):
        value, region = normalize_phone_with_candidates(
            "+44 7911 123456",
            candidate_regions=["IN"],
            fallback_region="US",
        )
        assert value == "+447911123456"
        assert region is None

    def test_candidate_region_garbage_returns_none(self):
        assert normalize_phone_with_candidates("not-a-phone", ["GB"], fallback_region="US") == (None, None)


# ======================================================================
# Date normalizer
# ======================================================================

class TestNormalizeDate:
    def test_iso_full(self):
        assert normalize_date("2020-03-15") == ("2020-03", "exact")

    def test_iso_month(self):
        assert normalize_date("2020-03") == ("2020-03", "exact")

    def test_slash_format(self):
        assert normalize_date("03/2020") == ("2020-03", "exact")

    def test_month_year(self):
        assert normalize_date("March 2020") == ("2020-03", "exact")

    def test_abbreviated_month(self):
        assert normalize_date("Mar 2020") == ("2020-03", "exact")

    def test_year_only(self):
        assert normalize_date("2020") == ("2020-01", "year_only_approximated")

    def test_present(self):
        assert normalize_date("Present") == (None, "present")

    def test_current(self):
        assert normalize_date("Current") == (None, "present")

    def test_none(self):
        assert normalize_date(None) == (None, "present")

    def test_empty(self):
        assert normalize_date("") == (None, "present")

    def test_unparseable(self):
        assert normalize_date("sometime last year") == (None, "unparseable")


# ======================================================================
# Country normalizer
# ======================================================================

class TestNormalizeCountry:
    def test_alpha2(self):
        assert normalize_country("US") == "US"

    def test_alpha3(self):
        assert normalize_country("USA") == "US"

    def test_full_name(self):
        assert normalize_country("United States") == "US"

    def test_uk_alias(self):
        # pycountry maps 'UK' as alpha-2 for Ukraine, not Great Britain.
        # 'GB' or 'United Kingdom' are the correct inputs for Great Britain.
        assert normalize_country("GB") == "GB"
        assert normalize_country("United Kingdom") == "GB"

    def test_informal_name(self):
        assert normalize_country("United States of America") == "US"

    def test_unmappable_returns_none(self):
        assert normalize_country("Narnia") is None

    def test_empty_returns_none(self):
        assert normalize_country("") is None
        assert normalize_country(None) is None

    def test_india(self):
        assert normalize_country("India") == "IN"


# ======================================================================
# Skills normalizer
# ======================================================================

class TestNormalizeSkill:
    def test_exact_synonym(self):
        assert normalize_skill("js") == ("JavaScript", True)

    def test_react_js(self):
        assert normalize_skill("react.js") == ("React", True)

    def test_k8s(self):
        assert normalize_skill("k8s") == ("Kubernetes", True)

    def test_unknown_skill_passthrough(self):
        name, verified = normalize_skill("SomeFancyTool")
        assert name == "Somefancytool"  # Title-cased.
        assert verified is False

    def test_case_insensitive(self):
        assert normalize_skill("PYTHON") == ("Python", True)

    def test_empty_returns_as_is(self):
        name, verified = normalize_skill("")
        assert name == ""
        assert verified is False


# ======================================================================
# Email normalizer
# ======================================================================

class TestNormalizeEmail:
    def test_valid_email(self):
        assert normalize_email("Jane.Doe@Example.COM") == "jane.doe@example.com"

    def test_with_whitespace(self):
        assert normalize_email("  user@test.com  ") == "user@test.com"

    def test_malformed_email_returns_none(self):
        assert normalize_email("invalid-email-format") is None

    def test_missing_tld_returns_none(self):
        assert normalize_email("user@") is None

    def test_empty_returns_none(self):
        assert normalize_email("") is None
        assert normalize_email(None) is None


# ======================================================================
# Name normalizer
# ======================================================================

class TestNormalizeName:
    def test_title_case(self):
        assert normalize_name("jane doe") == "Jane Doe"

    def test_trim_whitespace(self):
        assert normalize_name("  jane doe  ") == "Jane Doe"

    def test_collapse_whitespace(self):
        assert normalize_name("jane    doe") == "Jane Doe"

    def test_already_correct(self):
        assert normalize_name("Jane Doe") == "Jane Doe"

    def test_all_caps(self):
        assert normalize_name("JANE DOE") == "Jane Doe"

    def test_empty_returns_none(self):
        assert normalize_name("") is None
        assert normalize_name(None) is None
        assert normalize_name("   ") is None
