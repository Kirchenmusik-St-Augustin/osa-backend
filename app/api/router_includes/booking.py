from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.core import mailer
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.booking import (
    BookingStatusOutput,
    CastFormData,
    CastSaveRequest,
    MessageRecipientOutput,
    PerformanceBillingResponse,
    PerformanceCastPageResponse,
    PerformanceMessageToCastResponse,
    PerformanceRequestsAndBookingsResponse,
    SendMessageRequest,
)
from app.services import booking_service
from app.services.booking_service import (
    BookingRequestAlreadyExistsError,
    MessageRecipientsEmptyError,
)
from app.services.performance_service import (
    PerformanceInPastError,
    PerformanceNotFoundError,
)

booking_router = APIRouter()

_CAST = Depends(require_permission("performanceCast"))
_MAINTAIN = Depends(require_permission("performanceMaintain"))
_BILLING = Depends(require_permission("performanceBilling"))
_CHANGE_STATUS = Depends(require_permission("performanceChangeUserStatus"))

_NOT_FOUND_DETAIL = "Nicht gefunden."
_IN_PAST_DETAIL = "Die Aufführung liegt bereits in der Vergangenheit."
_DUPLICATE_REQUEST_DETAIL = "Es liegt bereits eine offene Anfrage vor."
_EMPTY_RECIPIENTS_DETAIL = "Keiner der Empfänger hat eine bestätigte E-Mail-Adresse."


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
    )


def _in_past() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_IN_PAST_DETAIL)


@booking_router.get("/{performance_id}/cast")
def get_cast_page(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _CAST],
) -> PerformanceCastPageResponse:
    try:
        return booking_service.get_cast_page(db, performance_id)
    except PerformanceNotFoundError:
        raise _not_found() from None
    except PerformanceInPastError:
        raise _in_past() from None


@booking_router.post("/{performance_id}/cast")
def save_cast(
    performance_id: int,
    data: CastSaveRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _CAST],
) -> CastFormData:
    try:
        return booking_service.save_cast(db, performance_id, data)
    except PerformanceNotFoundError:
        raise _not_found() from None
    except PerformanceInPastError:
        raise _in_past() from None


@booking_router.post("/{performance_id}/booking-status")
def change_user_request_status(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _CHANGE_STATUS],
    background_tasks: BackgroundTasks,
) -> BookingStatusOutput:
    """No request body -- the server recomputes the user's own current
    status and dispatches the transition itself (see
    booking_service.change_user_request_status's docstring)."""
    try:
        result, notification = booking_service.change_user_request_status(
            db, performance_id, current_user
        )
    except PerformanceNotFoundError:
        raise _not_found() from None
    except PerformanceInPastError:
        raise _in_past() from None
    except BookingRequestAlreadyExistsError:
        # Defensive only -- unreachable via the normal state machine (see
        # booking_service._request_booking's docstring), but a genuine
        # concurrent double-click must not surface as a raw 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_DUPLICATE_REQUEST_DETAIL
        ) from None

    if notification is not None:
        background_tasks.add_task(
            mailer.send_booked_or_standby_canceled_email,
            notification.disponent_emails,
            notification.canceling_user_name,
            notification.entry,
        )
    return result


@booking_router.get("/{performance_id}/my-booking-status")
def get_my_booking_status(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _CHANGE_STATUS],
) -> BookingStatusOutput:
    try:
        return booking_service.get_my_booking_status(
            db, performance_id, current_user.id
        )
    except PerformanceNotFoundError:
        raise _not_found() from None


@booking_router.get("/{performance_id}/billing")
def get_billing(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _BILLING],
) -> PerformanceBillingResponse:
    try:
        return booking_service.get_billing(db, performance_id, current_user)
    except PerformanceNotFoundError:
        raise _not_found() from None


@booking_router.get("/{performance_id}/requests-and-bookings")
def get_requests_and_bookings(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _MAINTAIN],
) -> PerformanceRequestsAndBookingsResponse:
    try:
        return booking_service.get_requests_and_bookings(
            db, performance_id, current_user
        )
    except PerformanceNotFoundError:
        raise _not_found() from None
    except PerformanceInPastError:
        raise _in_past() from None


@booking_router.get("/{performance_id}/message-to-cast")
def get_message_to_cast_page(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _MAINTAIN],
) -> PerformanceMessageToCastResponse:
    try:
        return booking_service.get_message_to_cast_page(
            db, performance_id, current_user
        )
    except PerformanceNotFoundError:
        raise _not_found() from None


@booking_router.get("/{performance_id}/message-to-cast/recipients")
def get_message_recipients(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
    position_type: Annotated[
        Literal["all", "instruments", "voices", "choirjobs"] | None, Query(alias="type")
    ] = None,
    position_id: Annotated[int | None, Query(alias="id")] = None,
) -> list[MessageRecipientOutput]:
    resolved_type = None if position_type in (None, "all") else position_type
    try:
        return booking_service.get_message_recipients(
            db, performance_id, resolved_type, position_id
        )
    except PerformanceNotFoundError:
        raise _not_found() from None


@booking_router.post("/{performance_id}/message-to-cast/send")
def send_message_to_cast(
    performance_id: int,
    data: SendMessageRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _MAINTAIN],
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    try:
        to_emails, sender_name, message = booking_service.send_message_to_cast(
            db, performance_id, current_user, data
        )
    except PerformanceNotFoundError:
        raise _not_found() from None
    except MessageRecipientsEmptyError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_EMPTY_RECIPIENTS_DETAIL,
        ) from None

    background_tasks.add_task(
        mailer.send_user_message_email, to_emails, sender_name, message
    )
    return {"status": "ok", "message": "Nachricht wurde versendet."}
