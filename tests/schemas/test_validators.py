import pytest

from app.schemas.validators import (
    password_policy_violations,
    validate_confirmation,
    validate_password_policy,
)


class TestPasswordPolicyViolations:
    def test_compliant_password_has_no_violations(self):
        assert password_policy_violations("Passw0rd1") == []

    def test_every_allowed_special_character_is_accepted(self):
        assert password_policy_violations("Ab1./+!@:_-x") == []

    @pytest.mark.parametrize("value", ["Ab1defg", "Abcdefghij1234567"])
    def test_length_outside_8_to_16_reports_only_the_length_rule(self, value: str):
        assert password_policy_violations(value) == [
            "Das Passwort muss zwischen 8 und 16 Zeichen lang sein."
        ]

    def test_forbidden_character_reports_only_the_charset_rule(self):
        violations = password_policy_violations("Passw0rd 1")
        assert len(violations) == 1
        assert "unzulässige Zeichen" in violations[0]

    def test_trailing_newline_is_a_forbidden_character(self):
        violations = password_policy_violations("Passw0rd1\n")
        assert len(violations) == 1
        assert "unzulässige Zeichen" in violations[0]

    def test_missing_letter_reports_only_the_letter_rule(self):
        assert password_policy_violations("12345678") == [
            "Das Passwort muss mindestens einen Buchstaben enthalten."
        ]

    def test_missing_digit_reports_only_the_digit_rule(self):
        assert password_policy_violations("Abcdefgh") == [
            "Das Passwort muss mindestens eine Ziffer enthalten."
        ]

    def test_all_violated_rules_are_reported_together(self):
        violations = password_policy_violations("ä")
        assert len(violations) == 4


class TestValidatePasswordPolicy:
    def test_returns_a_compliant_value_unchanged(self):
        assert validate_password_policy("Passw0rd1") == "Passw0rd1"

    def test_error_names_every_violated_rule(self):
        with pytest.raises(ValueError, match="Zeichen lang sein") as exc_info:
            validate_password_policy("short")
        assert "mindestens eine Ziffer" in str(exc_info.value)
        assert "Richtlinien" not in str(exc_info.value)


class TestValidateConfirmation:
    def test_matching_confirmation_passes(self):
        assert validate_confirmation("Passw0rd1", "Passw0rd1") == "Passw0rd1"

    def test_mismatch_is_rejected(self):
        with pytest.raises(ValueError, match="Passwort-Bestätigung"):
            validate_confirmation("Passw0rd1", "Other1234")

    def test_missing_other_value_is_a_mismatch(self):
        with pytest.raises(ValueError, match="Passwort-Bestätigung"):
            validate_confirmation("Passw0rd1", None)
