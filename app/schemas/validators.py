"""Shared field-validation rules, used across Auth/User/Profile schemas."""

import re
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from app.schemas.base import BlankToNone

# Optional leading "+", then 4-60 digits, spaces, slashes, parentheses or
# hyphens, at least four of them digits. Match it with fullmatch(): a "$"
# anchor would also accept a trailing newline. Single fixed error message
# regardless of which sub-condition fails.
PHONE_PATTERN = re.compile(r"\+?(?=(?:\D*\d){4})[0-9 /()-]{4,60}")


def lowercase_email(value: str | None) -> str | None:
    """Addresses are stored and compared in lower case (the database
    enforces it with a CHECK constraint), so every input that writes one
    normalises it first."""
    return value.lower() if value else value


PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 64
# bcrypt hashes at most 72 bytes of input, and multi-byte characters count
# once per byte: a password within the character limit can still be too long.
PASSWORD_MAX_BYTES = 72

# User-facing error text, not a credential. The "must differ from the
# current password" rule needs the stored password hash to compare against,
# so it can't live in a Pydantic field validator; see
# app.services.profile_service.update_profile().
PASSWORD_UNCHANGED_MESSAGE = (
    "Das neue Passwort muss sich vom bestehenden Passwort unterscheiden."  # noqa: S105
)


def _fits_bcrypt_input(value: str) -> bool:
    try:
        return len(value.encode("utf-8")) <= PASSWORD_MAX_BYTES
    except UnicodeEncodeError:
        return False


def password_policy_violations(value: str) -> list[str]:
    """Every password rule `value` violates, one specific message per rule
    (an empty list means compliant): 10-64 characters, valid text of at most
    72 bytes in UTF-8, and no character-class rules (length is what counts,
    passphrases and password-manager output are welcome). The "must differ
    from the current password" rule is deliberately NOT checked here, see
    PASSWORD_UNCHANGED_MESSAGE."""
    violations: list[str] = []
    if not PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH:
        violations.append(
            f"Das Passwort muss zwischen {PASSWORD_MIN_LENGTH} und "
            f"{PASSWORD_MAX_LENGTH} Zeichen lang sein."
        )
    if not _fits_bcrypt_input(value):
        violations.append(
            f"Das Passwort darf nur gültige Zeichen enthalten und höchstens "
            f"{PASSWORD_MAX_BYTES} Byte lang sein "
            "(Umlaute und Sonderzeichen zählen mehrfach)."
        )
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


def validate_phone(value: str) -> str:
    if not PHONE_PATTERN.fullmatch(value):
        msg = "Das Rufnummern-Format ist ungültig."
        raise ValueError(msg)
    return value


# A phone number without the blanks around it. OptionalPhoneNumber turns an
# empty (or whitespace-only) value into None, for the form where the number is
# optional.
PhoneNumber = Annotated[
    str, StringConstraints(strip_whitespace=True), AfterValidator(validate_phone)
]
OptionalPhoneNumber = Annotated[PhoneNumber | None, BlankToNone]
