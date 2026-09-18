"""Shared field-validation rules, used across Auth/User/Profile schemas.

Each schema still declares its own @field_validator with its own error text
where the wording differs per form for the identical rule (e.g. phone)."""

import re

# Optional leading "+", then 4-60 digits, spaces, slashes, parentheses or
# hyphens. Single fixed error message regardless of which sub-condition
# fails.
PHONE_PATTERN = re.compile(r"^\+?[0-9 /()-]{4,60}$")

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 16
_PASSWORD_FORBIDDEN_CHARACTER_PATTERN = re.compile(r"[^a-zA-Z0-9./+!@:_-]")
_LETTER_PATTERN = re.compile(r"[a-zA-Z]")
_DIGIT_PATTERN = re.compile(r"[0-9]")

# User-facing error text, not a credential. The "must differ from the
# current password" rule needs the stored password hash to compare against,
# so it can't live in a Pydantic field validator; see
# app.services.profile_service.update_profile().
PASSWORD_UNCHANGED_MESSAGE = (
    "Das neue Passwort muss sich vom bestehenden Passwort unterscheiden."  # noqa: S105
)


def password_policy_violations(value: str) -> list[str]:
    """Every password rule `value` violates, one specific message per rule
    (an empty list means compliant): 8-16 characters, only letters, digits
    and `. / + ! @ : _ -`, at least one letter AND one digit. The "must
    differ from the current password" rule is deliberately NOT checked
    here, see PASSWORD_UNCHANGED_MESSAGE."""
    violations: list[str] = []
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        violations.append(
            f"Das Passwort muss zwischen {PASSWORD_MIN_LENGTH} und "
            f"{PASSWORD_MAX_LENGTH} Zeichen lang sein."
        )
    if _PASSWORD_FORBIDDEN_CHARACTER_PATTERN.search(value):
        violations.append(
            "Das Passwort enthält unzulässige Zeichen "
            "(erlaubt sind Buchstaben, Ziffern und . / + ! @ : _ -)."
        )
    if not _LETTER_PATTERN.search(value):
        violations.append("Das Passwort muss mindestens einen Buchstaben enthalten.")
    if not _DIGIT_PATTERN.search(value):
        violations.append("Das Passwort muss mindestens eine Ziffer enthalten.")
    return violations


def validate_password_policy(value: str) -> str:
    """Field-validator body: raises one error naming every violated rule."""
    violations = password_policy_violations(value)
    if violations:
        raise ValueError(" ".join(violations))
    return value


def validate_confirmation(value: str, other: str | None) -> str:
    if value != other:
        msg = "Die Passwort-Bestätigung stimmt nicht überein."
        raise ValueError(msg)
    return value
