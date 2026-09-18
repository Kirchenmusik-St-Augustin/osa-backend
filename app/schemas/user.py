import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import LenientUuid, OptionalText, StrictInputModel
from app.schemas.performance import PositionRefOutput
from app.schemas.validators import PHONE_PATTERN


class RoleRefOutput(BaseModel):
    id: uuid.UUID
    name: str
    label: str


class Oauth2BindingOutput(BaseModel):
    id: uuid.UUID
    provider: str
    remote_name: str


class UserSearchResultOutput(BaseModel):
    id: uuid.UUID
    label: str


class UserFormOptionsOutput(BaseModel):
    """Catalog lists for the Instrument/Voice/Choirjob/Role picker widgets
    in the Create/Edit form -- reuses coreelement_service.list_coreelements()
    (see user_service.get_form_options()), independent of any one user."""

    instruments: list[PositionRefOutput]
    voices: list[PositionRefOutput]
    choirjobs: list[PositionRefOutput]
    roles: list[RoleRefOutput]


class UserRequest(StrictInputModel):
    """Admin-side user create/update body. Email is deliberately Optional
    -- `users.email` is DB-nullable. `roles` is accepted from every caller
    but only actually persisted for a real administrator -- see
    user_service.update_user(). `administrator` follows the same pattern:
    only an acting administrator can grant it, and only ever grant (see
    user_service._apply_administrator_grant())."""

    givenname: str = Field(min_length=3, max_length=32)
    surname: str = Field(min_length=3, max_length=32)
    email: EmailStr | None = Field(default=None, max_length=190)
    phone: OptionalText = None
    auth_locked: bool = False
    instruments: list[LenientUuid] = Field(default_factory=list)
    voices: list[LenientUuid] = Field(default_factory=list)
    choirjobs: list[LenientUuid] = Field(default_factory=list)
    roles: list[LenientUuid] = Field(default_factory=list)
    administrator: bool = False

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is not None and not PHONE_PATTERN.match(value):
            msg = "Das Rufnummern-Format ist ungültig."
            raise ValueError(msg)
        return value


class UserResponse(BaseModel):
    """Covers both Show and the Edit-form's prefill -- same pattern as
    Artist (see artist_service.get_artist() / ArtistResponse)."""

    id: uuid.UUID
    surname: str
    givenname: str
    email: str | None
    email_verified_at: UtcDatetime | None
    phone: str | None
    auth_lastsignal: UtcDatetime | None
    auth_locked: bool
    administrator: bool
    deletable: bool
    oauth2_bindings: list[Oauth2BindingOutput]
    instruments: list[PositionRefOutput]
    voices: list[PositionRefOutput]
    choirjobs: list[PositionRefOutput]
    roles: list[RoleRefOutput]
