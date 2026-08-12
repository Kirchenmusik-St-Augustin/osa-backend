from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import StrictInputModel
from app.schemas.performance import PositionRefOutput
from app.schemas.validators import PHONE_PATTERN


class RoleRefOutput(BaseModel):
    id: int
    name: str
    label: str


class Oauth2BindingOutput(BaseModel):
    id: int
    provider: str
    remote_name: str


class UserSearchResultOutput(BaseModel):
    id: int
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
    """Mirrors Legacy's Content/System/UserController SaveRequest. Email is
    deliberately Optional -- `users.email` is DB-nullable and Legacy's own
    `required_if:doReset,true` rule is dead code (the `doReset` field is
    never sent by the frontend), so the real, observable business result is
    that email stays optional here too (see project_osa_migration_plan
    memory). `roles` is accepted from every caller but only actually
    persisted for a real administrator -- see user_service.update_user().
    `administrator` follows the same pattern -- a deliberate divergence
    from Legacy (which has no such field/path at all): only an acting
    administrator can grant it, and only ever grant (see
    user_service._apply_administrator_grant())."""

    givenname: str = Field(min_length=3, max_length=32)
    surname: str = Field(min_length=3, max_length=32)
    email: EmailStr | None = Field(default=None, max_length=190)
    phone: str | None = None
    auth_locked: bool = False
    instruments: list[int] = Field(default_factory=list)
    voices: list[int] = Field(default_factory=list)
    choirjobs: list[int] = Field(default_factory=list)
    roles: list[int] = Field(default_factory=list)
    administrator: bool = False

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, value: str | None) -> str | None:
        if value is not None and not PHONE_PATTERN.match(value):
            msg = "Das Rufnummern-Format ist ungültig."
            raise ValueError(msg)
        return value


class UserResponse(BaseModel):
    """Covers both Show and the Edit-form's prefill -- 1:1 the pattern
    already established for Artist (see artist_service.get_artist() /
    ArtistResponse)."""

    id: int
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
