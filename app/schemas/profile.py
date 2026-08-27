from pydantic import EmailStr, Field, field_validator, model_validator

from app.schemas.base import StrictInputModel
from app.schemas.validators import (
    PHONE_PATTERN,
    validate_confirmation,
    validate_password_policy,
)


class ProfileUpdateRequest(StrictInputModel):
    """Mirrors Legacy's Selfadmin/ProfileController UpdateRequest. Unlike
    System::UserController's UserRequest, email and phone are PFLICHT here
    -- a deliberate Legacy rule difference, not a typo. `auth_password`
    (the user's CURRENT password) is always required -- every profile
    change, even just a phone number, must be re-authenticated."""

    givenname: str = Field(min_length=3, max_length=32)
    surname: str = Field(min_length=3, max_length=32)
    email: EmailStr = Field(max_length=190)
    phone: str
    change_password: bool
    password: str | None = None
    password_confirmation: str | None = None
    auth_password: str = Field(min_length=1)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str) -> str:
        if not PHONE_PATTERN.match(value):
            msg = "Das Rufnummern-Format ist ungültig."
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _validate_password_change(self) -> "ProfileUpdateRequest":
        # Mirrors Legacy's controller-level short-circuit
        # (`$validated['change_password'] && strlen($validated['password'])`)
        # -- password/password_confirmation are only validated (charset,
        # confirmation match) when a password change was actually
        # requested; an untouched change_password=false submission ignores
        # whatever those two fields happen to hold.
        if not self.change_password:
            return self
        if not self.password:
            msg = "Dieses Feld ist erforderlich."
            raise ValueError(msg)
        validate_password_policy(self.password)
        validate_confirmation(self.password_confirmation or "", self.password)
        return self
