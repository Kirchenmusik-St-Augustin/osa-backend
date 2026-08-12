from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.request_log import (
    RequestLogDayGroupOutput,
    RequestLogShowOutput,
    RequestLogUserDetailOutput,
)
from app.services import request_log_service
from app.services.request_log_service import (
    RequestLogNotFoundError,
    RequestLogUserNotFoundError,
)

request_log_router = APIRouter()

_VIEW = Depends(require_permission("requestLogView"))
_NOT_FOUND_DETAIL = "Nicht gefunden."
_INVALID_DAY_DETAIL = "Ungültiges Datum."


def _require_calendar_day(
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    day: Annotated[int, Query(ge=1, le=31)],
) -> date:
    """FastAPI dependency, not business logic: year/month/day together must
    form a real calendar date (e.g. rejects 2026-02-30). Query()'s ge/le
    bounds above already reject each field's own out-of-range value
    (day=32 etc.) via FastAPI's own RequestValidationError before this body
    ever runs -- this only catches in-bounds-but-invalid *combinations*, the
    same category of request-shape validation as those bounds themselves,
    so it stays router-level rather than moving into request_log_service
    (no DB access happens here)."""
    try:
        return date(year, month, day)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_INVALID_DAY_DETAIL,
        ) from None


_DAY = Depends(_require_calendar_day)


@request_log_router.get("")
def list_request_log_users(
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> list[RequestLogDayGroupOutput]:
    return request_log_service.list_days_with_users_for_month(db, year, month)


@request_log_router.get("/users/{user_id}")
def get_request_logs_for_user(
    user_id: int,
    day: Annotated[date, _DAY],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _VIEW],
) -> RequestLogUserDetailOutput:
    try:
        return request_log_service.list_entries_for_user_day(db, user_id, day)
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
