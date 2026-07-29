from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.deps import get_current_user
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.performance import (
    PerformanceAvailableData,
    PerformanceCalendarItem,
    PerformanceFormData,
    PerformanceRequest,
    PerformanceResponse,
    PerformanceShowResponse,
)
from app.services import performance_service
from app.services.performance_service import (
    PerformanceInPastError,
    PerformanceNotFoundError,
    PerformanceValidationError,
)

performance_router = APIRouter()

_MAINTAIN = Depends(require_permission("performanceMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."
_IN_PAST_DETAIL = "Die Aufführung liegt bereits in der Vergangenheit."


@performance_router.get("")
def list_performances(
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> list[PerformanceCalendarItem]:
    return list(performance_service.list_performances_for_month(db, year, month))


@performance_router.get("/available")
def get_available_data(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceAvailableData:
    return performance_service.get_available_data(db)


@performance_router.get("/{performance_id}")
def get_performance(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_current_user)],
) -> PerformanceShowResponse:
    try:
        return performance_service.get_performance_detail(db, performance_id)
    except PerformanceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None


@performance_router.get("/{performance_id}/form")
def get_performance_form_data(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceFormData:
    try:
        return performance_service.get_form_data(db, performance_id)
    except PerformanceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except PerformanceInPastError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_IN_PAST_DETAIL
        ) from None


@performance_router.post("", status_code=status.HTTP_201_CREATED)
def create_performance(
    data: PerformanceRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceResponse:
    try:
        return performance_service.create_performance(db, data)
    except PerformanceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@performance_router.put("/{performance_id}")
def update_performance(
    performance_id: int,
    data: PerformanceRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceResponse:
    try:
        return performance_service.update_performance(db, performance_id, data)
    except PerformanceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except PerformanceInPastError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_IN_PAST_DETAIL
        ) from None
    except PerformanceValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@performance_router.delete("/{performance_id}")
def delete_performance(
    performance_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    try:
        performance_service.delete_performance(db, performance_id)
    except PerformanceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except PerformanceInPastError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_IN_PAST_DETAIL
        ) from None
    return {"status": "ok", "message": "Element wurde gelöscht."}
