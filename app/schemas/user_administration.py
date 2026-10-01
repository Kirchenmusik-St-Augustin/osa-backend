import uuid

from pydantic import BaseModel

from app.core.datetime_utils import UtcDatetime


class UserAdministrationSearchResultOutput(BaseModel):
    id: uuid.UUID
    label: str


class UserAdministrationDeletedEntryOutput(BaseModel):
    """One soft-deleted user in the initial list -- deliberately thinner
    than the search result (no `label`, a plain `email`)."""

    id: uuid.UUID
    surname: str
    givenname: str
    email: str | None


class UserAdministrationDetailOutput(BaseModel):
    """Deliberately thinner than user_service's UserResponse (no abilities, roles
    or bindings): the Administration domain only needs contact data, status flags
    and the three actions."""

    id: uuid.UUID
    surname: str
    givenname: str
    email: str | None
    phone: str | None
    email_verified_at: UtcDatetime | None
    auth_locked: bool
    deleted_at: UtcDatetime | None
    auth_lastsignal: UtcDatetime | None
    purgeable: bool


class UserAdministrationActionResponse(BaseModel):
    user: UserAdministrationDetailOutput
    newpw: str | None = None
