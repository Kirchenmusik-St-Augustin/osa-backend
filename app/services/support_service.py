from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.human_names import label_for_name
from app.db.models.role import Role
from app.db.models.user import User
from app.schemas.support import (
    ContactUserOutput,
    MessageToContactpersonRequest,
    RoleWithContactsOutput,
)
from app.services import booking_service

if TYPE_CHECKING:
    from app.schemas.booking import PerformanceShortOutput


def get_my_requests_and_bookings(
    db: Session, user: User
) -> list[PerformanceShortOutput]:
    """Thin wrapper: the caller's own upcoming requests and bookings."""
    return booking_service.get_upcoming_requests_and_bookings_for_user(db, user.id)


def list_roles_with_contacts(db: Session) -> list[RoleWithContactsOutput]:
    """All roles with their contact users. Single query via
    `selectinload(Role.users)` -- N+1-safe regardless of how many
    roles/contacts exist (see app.db.models.role.Role.users docstring).

    Contacts are re-sorted by (surname, givenname) in Python after loading,
    so the dropdown is alphabetical regardless of `user_roles` insertion
    order."""
    roles = (
        db.execute(select(Role).options(selectinload(Role.users)).order_by(Role.id))
        .scalars()
        .all()
    )
    return [
        RoleWithContactsOutput(
            id=role.id,
            name=role.name,
            label=role.label,
            description=role.description,
            users=[
                ContactUserOutput(
                    id=contact.id,
                    givenname=contact.givenname,
                    surname=contact.surname,
                    has_email=contact.email is not None
                    and contact.email_verified_at is not None,
                )
                for contact in sorted(
                    role.users, key=lambda contact: (contact.surname, contact.givenname)
                )
            ],
        )
        for role in roles
    ]


def send_message_to_contactperson(
    db: Session, sender: User, data: MessageToContactpersonRequest
) -> tuple[list[str], str, str] | None:
    """Looks up the recipient and only returns mail data if the recipient
    exists and has a verified email -- otherwise it silently no-ops (the
    router responds 200 either way, which does not reveal whether a given
    recipient id exists or is verified).

    Returns (to_emails, sender_name, message) for the ROUTER to schedule via
    `BackgroundTasks.add_task(mailer.send_user_message_email, ...)` -- same
    framework-agnostic split as booking_service.send_message_to_cast."""
    recipient = db.get(User, data.recipient_id)
    if (
        recipient is None
        or recipient.email is None
        or recipient.email_verified_at is None
    ):
        return None
    return (
        [recipient.email],
        label_for_name(sender.surname, sender.givenname),
        data.message,
    )
