import pytest

from app.schemas.validators import (
    password_policy_violations,
    validate_confirmation,
    validate_password_policy,
)


class TestPasswordPolicyViolations:
    @pytest.mark.parametrize(
        "value",
        [
            "a" * 10,
            "a" * 64,
            "korrekt pferd batterie",
            "Ab1./+!@:_-x#$%&",
            "nurbuchstaben",
            "1234567890",
            "Übergrößenträger",
        ],
    )
    def test_compliant_password_has_no_violations(self, value: str):
        assert password_policy_violations(value) == []

    @pytest.mark.parametrize("value", ["a" * 9, "", "a" * 65])
    def test_length_outside_10_to_64_reports_only_the_length_rule(self, value: str):
        assert password_policy_violations(value) == [
            "Das Passwort muss zwischen 10 und 64 Zeichen lang sein."
        ]

    def test_exactly_72_bytes_are_accepted(self):
        assert password_policy_violations("ä" * 36) == []

    @pytest.mark.parametrize("value", ["ä" * 36 + "a", "😀" * 19, "ä" * 40])
    def test_more_than_72_bytes_within_the_character_limit_reports_only_the_byte_rule(
        self, value: str
    ):
        violations = password_policy_violations(value)
        assert len(violations) == 1
        assert "höchstens 72 Byte" in violations[0]

    def test_text_that_cannot_be_encoded_reports_the_byte_rule(self):
        violations = password_policy_violations("a" * 9 + "\ud800")
        assert len(violations) == 1
        assert "gültige Zeichen" in violations[0]

    def test_both_rules_are_reported_together(self):
        assert len(password_policy_violations("ä" * 65)) == 2


class TestValidatePasswordPolicy:
    def test_returns_a_compliant_value_unchanged(self):
        assert validate_password_policy("Passw0rd12") == "Passw0rd12"

    def test_error_names_every_violated_rule(self):
        with pytest.raises(ValueError, match="Zeichen lang sein") as exc_info:
            validate_password_policy("ä" * 65)
        assert "höchstens 72 Byte" in str(exc_info.value)
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
