from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.request_log import (
    RequestLogShowOutput,
    RequestLogUserDetailOutput,
    RequestLogUserSummaryOutput,
)
from app.services import request_log_service
from app.services.request_log_service import (
    RequestLogNotFoundError,
    RequestLogUserNotFoundError,
)

request_log_router = APIRouter()

_VIEW = Depends(require_permission("requestLogView"))
_NOT_FOUND_DETAIL = "Nicht gefunden."


@request_log_router.get("")
def list_request_log_users(
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> list[RequestLogUserSummaryOutput]:
    return request_log_service.list_users_for_month(db, year, month)


@request_log_router.get("/users/{user_id}")
def get_request_logs_for_user(
    user_id: int,
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> RequestLogUserDetailOutput:
    try:
        return request_log_service.list_entries_for_user(db, user_id, year, month)
    except RequestLogUserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None


@request_log_router.get("/{request_log_id}")
def get_request_log(
    request_log_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> RequestLogShowOutput:
    try:
        return request_log_service.get(db, request_log_id)
    except RequestLogNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
