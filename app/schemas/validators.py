"""Shared field-validation patterns, used across Auth/User/Profile schemas.

Extracted from app.schemas.auth once a second (Schritt 7) and third (User-
domain) schema module needed the same phone regex -- each schema still
declares its own @field_validator with its own error text (Legacy shows a
different message per form for the identical rule)."""

import re

# Legacy's App\Rules\ValidPhone: `^\+?[0-9\ \/\(\)-]{4,60}$`, single fixed
# error message regardless of which sub-condition fails.
PHONE_PATTERN = re.compile(r"^\+?[0-9 /()-]{4,60}$")

# Legacy's App\Rules\Password\ValidNewPassword: 8-16 chars from this exact
# charset, at least one letter AND one digit. Same fixed error message for
# every sub-rule violation (Legacy shows one generic text, never
# specifying which part failed).
PASSWORD_CHARSET_PATTERN = re.compile(r"^[a-zA-Z0-9./+!@:_-]{8,16}$")

# User-facing error text, not a credential. Legacy's ValidNewPassword rule
# also reuses this exact message for its fourth sub-rule (new password must
# differ from the current one) -- that check needs a DB-backed password
# hash to compare against, so it can't live in a Pydantic field validator;
# see app.services.profile_service.update_profile().
PASSWORD_POLICY_MESSAGE = (
    "Das neue Passwort entspricht nicht den Richtlinien (8-16 Zeichen, "  # noqa: S105
    "mind. eine Ziffer, mind. ein Buchstabe. Muss sich vom bestehenden "
    "Passwort unterscheiden.)."
)


def validate_password_policy(value: str) -> str:
    """Charset/length/letter+digit sub-rules of Legacy's ValidNewPassword --
    the "must differ from current password" sub-rule is deliberately NOT
    checked here, see PASSWORD_POLICY_MESSAGE docstring above."""
    if (
        not PASSWORD_CHARSET_PATTERN.match(value)
        or not re.search(r"[a-zA-Z]", value)
        or not re.search(r"[0-9]", value)
    ):
        raise ValueError(PASSWORD_POLICY_MESSAGE)
    return value


def validate_confirmation(value: str, other: str | None) -> str:
    if value != other:
        msg = "Die Passwort-Bestätigung stimmt nicht überein."
        raise ValueError(msg)
    return value
