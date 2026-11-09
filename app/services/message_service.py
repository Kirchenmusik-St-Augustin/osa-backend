from typing import TYPE_CHECKING

from app.core.human_names import label_for_name
from app.schemas.booking import (
    CastSectionOutput,
    MessageRecipientOutput,
    PerformanceMessageToCastResponse,
    SendMessageRequest,
)
from app.services import performance_service
from app.services.booking_common import (
    get_performance_or_404,
    load_users_by_id,
    to_short_output,
)
from app.services.booking_status_service import user_booking_status
from app.services.cast_service import get_booked_cast

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.db.models.user import User
    from app.services.position_types import PositionType


class MessageRecipientsEmptyError(Exception):
    """Raised when none of the requested recipients have a verified email
    -- the "nothing to actually send" guard."""


def get_message_to_cast_page(
    db: Session, performance_id: uuid.UUID, current_user: User
) -> PerformanceMessageToCastResponse:
    """No past-lock -- the message-to-cast page stays available for past
    performances, unlike the maintain-type actions, whose object-level
    past-check locks them once the schedule has passed. Intentional."""
    performance = get_performance_or_404(db, performance_id)
    detail = performance_service.get_performance_detail(db, performance_id)
    setup = detail.setup
    booked_cast = get_booked_cast(db, performance, setup)
    user_booking = user_booking_status(db, performance, current_user.id)
    short = to_short_output(detail, user_booking)
    return PerformanceMessageToCastResponse(
        **short.model_dump(), booked_cast=booked_cast
    )


def _ordered_recipient_ids(
    booked_cast: CastSectionOutput,
    position_type: PositionType | None,
    position_id: uuid.UUID | None,
) -> list[uuid.UUID]:
    """Order: instruments, then voices, then choirjobs -- each item's cast
    is already sorted by position order + booking order."""
    if position_type is not None:
        section = getattr(booked_cast, position_type)
        item = next((entry for entry in section if entry.id == position_id), None)
        return [member.id for member in item.cast] if item is not None else []

    ordered_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for section in (booked_cast.instruments, booked_cast.voices, booked_cast.choirjobs):
        for item in section:
            for member in item.cast:
                if member.id in seen:
                    continue
                seen.add(member.id)
                ordered_ids.append(member.id)
    return ordered_ids


def get_message_recipients(
    db: Session,
    performance_id: uuid.UUID,
    position_type: PositionType | None,
    position_id: uuid.UUID | None,
) -> list[MessageRecipientOutput]:
    performance = get_performance_or_404(db, performance_id)
    setup = performance_service.get_setup(db, performance_id)
    booked_cast = get_booked_cast(db, performance, setup)

    ordered_ids = _ordered_recipient_ids(booked_cast, position_type, position_id)
    users_by_id = load_users_by_id(db, set(ordered_ids))
    return [
        MessageRecipientOutput(
            id=user.id,
            surname=user.surname,
            givenname=user.givenname,
            has_email=user.email_verified_at is not None,
            email=user.email if user.email_verified_at is not None else None,
            phone=user.phone,
        )
        for user_id in ordered_ids
        if (user := users_by_id.get(user_id)) is not None
    ]


def send_message_to_cast(
    db: Session, performance_id: uuid.UUID, sender: User, data: SendMessageRequest
) -> tuple[list[str], str, str]:
    """Sends a free-text message to the selected cast members, built on the
    shared mailer/template infrastructure (`user_message` template).

    Returns (to_emails, sender_name, message) for the ROUTER to schedule
    via `JobQueue.enqueue(send_user_message_email_task, ...)` -- the
    service layer stays framework-agnostic (no FastAPI import)."""
    performance = get_performance_or_404(db, performance_id)
    setup = performance_service.get_setup(db, performance_id)
    # Only people who are actually booked on this performance may be written
    # to: the client-supplied ids are an upper bound, never a mailing list.
    booked_ids = set(
        _ordered_recipient_ids(get_booked_cast(db, performance, setup), None, None)
    )
    users_by_id = load_users_by_id(db, booked_ids & set(data.recipient_ids))
    to_emails = [
        user.email
        for user in users_by_id.values()
        if user.email is not None
        and user.email_verified_at is not None
        and user.deleted_at is None
    ]
    if not to_emails:
        raise MessageRecipientsEmptyError
    return to_emails, label_for_name(sender.surname, sender.givenname), data.message
