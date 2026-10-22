import uuid

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import PersonName, StrictInputModel
from app.schemas.validators import (
    PhoneNumber,
    validate_confirmation,
    validate_password_policy,
)


class RegisterRequest(StrictInputModel):
    surname: PersonName
    givenname: PersonName
    email: EmailStr
    phone: PhoneNumber
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


class VerifyEmailRequest(StrictInputModel):
    token: str = Field(min_length=1)


class ForgotPasswordRequest(StrictInputModel):
    email: EmailStr


class ResetPasswordRequest(StrictInputModel):
    email: EmailStr
    token: str = Field(min_length=1)
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
    credential: str = Field(min_length=1)


class GoogleLinkRequest(StrictInputModel):
    credential: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class EmailKillSwitchStatusOutput(BaseModel):
    """Mirrors app.core.mailer.MailKillSwitchStatus, minus `sent` (the live
    counter belongs to the Statistics page, not every login) -- drives the
    navbar warning icon."""

    active: bool
    period_days: int
    threshold: int


class UserProfileResponse(BaseModel):
    """Output-only model (no extra="forbid"/strict=True -- that
    requirement targets input validation, not response serialization).
    Frontend-facing shape of "who am I": drives navbar display and
    permission-gated UI, since /auth/login itself returns only a JWT."""

    id: uuid.UUID
    email: str
    email_verified_at: UtcDatetime | None
    surname: str
    givenname: str
    administrator: bool
    permissions: list[str]
    email_kill_switch: EmailKillSwitchStatusOutput
