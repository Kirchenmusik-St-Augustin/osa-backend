from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.auth_guards import get_verified_user
from app.core import mailer
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.booking import PerformanceShortOutput
from app.schemas.support import MessageToContactpersonRequest, RoleWithContactsOutput
from app.services import support_service

support_router = APIRouter()


@support_router.get("/requests-and-bookings")
def get_my_requests_and_bookings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> list[PerformanceShortOutput]:
    """No permission gate beyond being logged in -- 1:1 Legacy's
    SupportController (every user manages only their own requests/
    bookings)."""
    return support_service.get_my_requests_and_bookings(db, current_user)


@support_router.get("/contactpersons")
def get_contactpersons(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_verified_user)],
) -> list[RoleWithContactsOutput]:
    """No permission gate beyond being logged in -- 1:1 Legacy's GET branch
    of messageToContactperson()."""
    return support_service.list_roles_with_contacts(db)


@support_router.post("/message-to-contactperson")
def send_message_to_contactperson(
    data: MessageToContactpersonRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Always responds 200 -- 1:1 Legacy's silent no-op for a missing/
    unverified recipient (see support_service.send_message_to_contactperson's
    docstring)."""
    result = support_service.send_message_to_contactperson(db, current_user, data)
    if result is not None:
        to_emails, sender_name, message = result
        background_tasks.add_task(
            mailer.send_user_message_email, to_emails, sender_name, message
        )
    return {"status": "ok", "message": "Nachricht wurde versendet."}
