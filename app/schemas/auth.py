import re

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.schemas.base import StrictInputModel

# Legacy's App\Rules\ValidPhone: `^\+?[0-9\ \/\(\)-]{4,60}$`, single fixed
# error message regardless of which sub-condition fails.
_PHONE_PATTERN = re.compile(r"^\+?[0-9 /()-]{4,60}$")

# Legacy's App\Rules\Password\ValidNewPassword: 8-16 chars from this exact
# charset, at least one letter AND one digit. Same fixed error message for
# every sub-rule violation (Legacy shows one generic text, never
# specifying which part failed).
_PASSWORD_CHARSET_PATTERN = re.compile(r"^[a-zA-Z0-9./+!@:_-]{8,16}$")
# User-facing error text, not a credential.
_PASSWORD_POLICY_MESSAGE = (
    "Das neue Passwort entspricht nicht den Richtlinien (8-16 Zeichen, "  # noqa: S105
    "mind. eine Ziffer, mind. ein Buchstabe. Muss sich vom bestehenden "
    "Passwort unterscheiden.)."
)


def _validate_password_policy(value: str) -> str:
    if (
        not _PASSWORD_CHARSET_PATTERN.match(value)
        or not re.search(r"[a-zA-Z]", value)
        or not re.search(r"[0-9]", value)
    ):
        raise ValueError(_PASSWORD_POLICY_MESSAGE)
    return value


def _validate_confirmation(value: str, info: ValidationInfo) -> str:
    if value != info.data.get("password"):
        msg = "Die Passwort-Bestätigung stimmt nicht überein."
        raise ValueError(msg)
    return value


class RegisterRequest(StrictInputModel):
    surname: str = Field(min_length=3, max_length=32)
    givenname: str = Field(min_length=3, max_length=32)
    email: EmailStr
    phone: str
    password: str
    password_confirmation: str

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        if not _PHONE_PATTERN.match(value):
            msg = "Ungültige Telefonnummer"
            raise ValueError(msg)
        return value

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        return _validate_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def _validate_password_confirmation(cls, value: str, info: ValidationInfo) -> str:
        return _validate_confirmation(value, info)


class VerifyEmailRequest(StrictInputModel):
    token: str


class ForgotPasswordRequest(StrictInputModel):
    email: EmailStr


class ResetPasswordRequest(StrictInputModel):
    email: EmailStr
    token: str
    password: str
    password_confirmation: str

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        return _validate_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def _validate_password_confirmation(cls, value: str, info: ValidationInfo) -> str:
        return _validate_confirmation(value, info)


class GoogleCallbackRequest(StrictInputModel):
    credential: str


class GoogleLinkRequest(StrictInputModel):
    credential: str
    email: EmailStr
    password: str


class UserProfileResponse(BaseModel):
    """Output-only model (no extra="forbid"/strict=True -- that CLAUDE.md
    requirement targets input validation, not response serialization).
    Frontend-facing shape of "who am I": drives navbar display and
    permission-gated UI, since /auth/login itself returns only a JWT."""

    id: int
    email: str
    surname: str
    givenname: str
    administrator: bool
    permissions: list[str]
