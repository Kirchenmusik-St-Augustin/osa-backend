from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_guards import get_verified_user
from app.api.job_queue import JobQueue, get_job_queue
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.booking import PerformanceShortOutput
from app.schemas.support import MessageToContactpersonRequest, RoleWithContactsOutput
from app.services import support_service
from app.worker.tasks import send_user_message_email_task

support_router = APIRouter()


@support_router.get("/requests-and-bookings")
def get_my_requests_and_bookings(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> list[PerformanceShortOutput]:
    """No permission gate beyond being logged in -- every user manages only
    their own requests/bookings."""
    return support_service.get_my_requests_and_bookings(db, current_user)


@support_router.get("/contactpersons")
def get_contactpersons(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_verified_user)],
) -> list[RoleWithContactsOutput]:
    """No permission gate beyond being logged in."""
    return support_service.list_roles_with_contacts(db)


@support_router.post("/message-to-contactperson")
def send_message_to_contactperson(
    data: MessageToContactpersonRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> dict[str, str]:
    """Always responds 200 -- a missing/unverified recipient is a silent
    no-op (see support_service.send_message_to_contactperson's
    docstring). get_verified_user is declared before job_queue on purpose,
    see get_job_queue."""
    result = support_service.send_message_to_contactperson(db, current_user, data)
    if result is not None:
        to_emails, sender_name, message = result
        job_queue.enqueue(send_user_message_email_task, to_emails, sender_name, message)
    return {"status": "ok", "message": "Nachricht wurde versendet."}
