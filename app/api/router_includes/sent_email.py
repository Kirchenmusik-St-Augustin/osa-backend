import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, require_permission
from app.api.query_params import CalendarYear, PageDep
from app.db.database import get_db
from app.schemas.pagination import Page
from app.schemas.sent_email import SentEmailShortOutput, SentEmailShowOutput
from app.services import sent_email_service
from app.services.sent_email_service import SentEmailNotFoundError

sent_email_router = APIRouter()

_VIEW = Depends(require_permission("sentEmailView"))
_NOT_FOUND_DETAIL = "Nicht gefunden."


@sent_email_router.get("")
def list_sent_emails(
    year: CalendarYear,
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _VIEW],
    page: PageDep,
) -> Page[SentEmailShortOutput]:
    return Page.of(sent_email_service.list_for_month(db, year, month, page), page)


@sent_email_router.get("/{sent_email_id}")
def get_sent_email(
    sent_email_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _VIEW],
) -> SentEmailShowOutput:
    try:
        return sent_email_service.get(db, sent_email_id)
    except SentEmailNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
