import uuid

from pydantic import BaseModel

from app.core.datetime_utils import UtcDatetime


class UserAdministrationSearchResultOutput(BaseModel):
    id: uuid.UUID
    label: str


class UserAdministrationDeletedEntryOutput(BaseModel):
    """Mirrors Legacy's User\\DeletedListEntry resource -- deliberately
    thinner than the search result (no `label`, a plain `email`)."""

    id: uuid.UUID
    surname: str
    givenname: str
    email: str | None


class UserAdministrationDetailOutput(BaseModel):
    """Mirrors Legacy's User\\ShowAdministration resource -- deliberately
    thinner than user_service's UserResponse (no phone, no abilities): the
    Administration domain only ever needs status flags + the three
    actions."""

    id: uuid.UUID
    surname: str
    givenname: str
    email: str | None
    email_verified_at: UtcDatetime | None
    auth_locked: bool
    deleted_at: UtcDatetime | None
    auth_lastsignal: UtcDatetime | None


class UserAdministrationActionResponse(BaseModel):
    user: UserAdministrationDetailOutput
    newpw: str | None = None
