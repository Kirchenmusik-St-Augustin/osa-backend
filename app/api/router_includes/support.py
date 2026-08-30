from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.auth_guards import get_verified_user
from app.core.arq_pool import get_arq_pool
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


def _send_message_to_contactperson_sync(
    db: Session, current_user: User, data: MessageToContactpersonRequest
) -> tuple[list[str], str, str] | None:
    return support_service.send_message_to_contactperson(db, current_user, data)


@support_router.post("/message-to-contactperson")
async def send_message_to_contactperson(
    data: MessageToContactpersonRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
    arq_pool: Annotated[ArqRedis, Depends(get_arq_pool)],
) -> dict[str, str]:
    """Always responds 200 -- 1:1 Legacy's silent no-op for a missing/
    unverified recipient (see support_service.send_message_to_contactperson's
    docstring). get_verified_user is declared before arq_pool on purpose --
    see profile.py's update_profile for why."""
    result = await run_in_threadpool(
        _send_message_to_contactperson_sync, db, current_user, data
    )
    if result is not None:
        to_emails, sender_name, message = result
        await arq_pool.enqueue_job(
            send_user_message_email_task.__name__, to_emails, sender_name, message
        )
    return {"status": "ok", "message": "Nachricht wurde versendet."}
