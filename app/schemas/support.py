from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class ContactUserOutput(BaseModel):
    """1:1 Legacy's `User\\Short` resource -- `has_email` mirrors
    `hasVerifiedEmail()`, not merely "an email is set"."""

    id: int
    givenname: str
    surname: str
    has_email: bool


class RoleWithContactsOutput(BaseModel):
    """1:1 Legacy's `Role\\ShowWithUsers` resource."""

    id: int
    name: str
    label: str
    description: str | None
    users: list[ContactUserOutput]


class MessageToContactpersonRequest(StrictInputModel):
    """1:1 Legacy's `MessageToContactpersonRequest` rules (`'message' =>
    ['required', 'min:3']`) -- `recipient_id` is required here (unlike
    Legacy's own unvalidated-if-absent `exists:` rule, see
    support_service.send_message_to_contactperson's docstring for why that
    Legacy quirk is not worth replicating literally)."""

    recipient_id: int
    message: str = Field(min_length=3)
