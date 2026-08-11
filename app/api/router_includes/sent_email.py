from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.sent_email import SentEmailShortOutput, SentEmailShowOutput
from app.services import sent_email_service
from app.services.sent_email_service import SentEmailNotFoundError

sent_email_router = APIRouter()

_VIEW = Depends(require_permission("sentEmailView"))
_NOT_FOUND_DETAIL = "Nicht gefunden."


@sent_email_router.get("")
def list_sent_emails(
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> list[SentEmailShortOutput]:
    return sent_email_service.list_for_month(db, year, month)


@sent_email_router.get("/{sent_email_id}")
def get_sent_email(
    sent_email_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> SentEmailShowOutput:
    try:
        return sent_email_service.get(db, sent_email_id)
    except SentEmailNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
