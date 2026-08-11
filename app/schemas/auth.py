from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.schemas.base import StrictInputModel
from app.schemas.validators import (
    PHONE_PATTERN,
    validate_confirmation,
    validate_password_policy,
)


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
        if not PHONE_PATTERN.match(value):
            msg = "Ungültige Telefonnummer"
            raise ValueError(msg)
        return value

    @field_validator("password")
    @classmethod
    def _validate_password(cls, value: str) -> str:
        return validate_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def _validate_password_confirmation(cls, value: str, info: ValidationInfo) -> str:
        return validate_confirmation(value, info.data.get("password"))


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
        return validate_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def _validate_password_confirmation(cls, value: str, info: ValidationInfo) -> str:
        return validate_confirmation(value, info.data.get("password"))


class GoogleCallbackRequest(StrictInputModel):
    credential: str


class GoogleLinkRequest(StrictInputModel):
    credential: str
    email: EmailStr
    password: str


class EmailKillSwitchStatusOutput(BaseModel):
    """Mirrors app.core.mailer.MailKillSwitchStatus, minus `sent` (the live
    counter belongs to the future Statistics page/Schritt 9, not every
    login) -- drives the navbar warning icon (Schritt 7)."""

    active: bool
    period_days: int
    threshold: int


class UserProfileResponse(BaseModel):
    """Output-only model (no extra="forbid"/strict=True -- that CLAUDE.md
    requirement targets input validation, not response serialization).
    Frontend-facing shape of "who am I": drives navbar display and
    permission-gated UI, since /auth/login itself returns only a JWT."""

    id: int
    email: str
    email_verified_at: datetime | None
    surname: str
    givenname: str
    administrator: bool
    permissions: list[str]
    email_kill_switch: EmailKillSwitchStatusOutput
