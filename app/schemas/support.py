import uuid

from pydantic import BaseModel, Field

from app.schemas.base import LenientUuid, StrictInputModel


class ContactUserOutput(BaseModel):
    """Contact person of a role -- `has_email` means the email is
    VERIFIED, not merely "an email is set"."""

    id: uuid.UUID
    givenname: str
    surname: str
    has_email: bool


class RoleWithContactsOutput(BaseModel):
    """A role together with its contact users."""

    id: uuid.UUID
    name: str
    label: str
    description: str | None
    users: list[ContactUserOutput]


class MessageToContactpersonRequest(StrictInputModel):
    """The message is embedded unmodified into an email body, so a
    max_length caps how much text a single request can push through the
    mail pipeline. `recipient_id` is required; an unknown or unverified
    recipient is a silent no-op, see
    support_service.send_message_to_contactperson."""

    recipient_id: LenientUuid
    message: str = Field(min_length=3, max_length=2000)
