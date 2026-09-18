from pydantic import (
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)

from app.schemas.base import StrictInputModel
from app.schemas.validators import (
    PHONE_PATTERN,
    validate_confirmation,
    validate_password_policy,
)


class ProfileUpdateRequest(StrictInputModel):
    """Self-service profile edit. Unlike the admin-side UserRequest, email
    and phone are REQUIRED here. `auth_password` (the user's CURRENT
    password) is always required -- every profile change, even just a phone
    number, must be re-authenticated. `password`/`password_confirmation` are
    only validated (policy, confirmation match) when a password change was
    actually requested; an untouched change_password=false submission
    ignores whatever those two fields happen to hold."""

    givenname: str = Field(min_length=3, max_length=32)
    surname: str = Field(min_length=3, max_length=32)
    email: EmailStr = Field(max_length=190)
    phone: str
    change_password: bool
    password: str | None = Field(default=None, validate_default=True)
    password_confirmation: str | None = Field(default=None, validate_default=True)
    auth_password: str = Field(min_length=1, max_length=128)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        if not PHONE_PATTERN.match(value):
            msg = "Das Rufnummern-Format ist ungültig."
            raise ValueError(msg)
        return value

    @field_validator("password")
    @classmethod
    def _validate_new_password(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if not info.data.get("change_password"):
            return value
        if not value:
            msg = "Dieses Feld ist erforderlich."
            raise ValueError(msg)
        return validate_password_policy(value)

    @field_validator("password_confirmation")
    @classmethod
    def _validate_new_password_confirmation(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        # A missing "password" means it already failed its own validation;
        # reporting a confirmation mismatch on top would only add noise.
        if not info.data.get("change_password") or "password" not in info.data:
            return value
        return validate_confirmation(value or "", info.data["password"])
