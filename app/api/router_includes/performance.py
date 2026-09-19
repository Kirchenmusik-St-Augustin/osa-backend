import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.auth_guards import get_verified_user, require_permission
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

performance_router = APIRouter()

_MAINTAIN = Depends(require_permission("performanceMaintain"))


@performance_router.get("")
def list_performances(
    year: Annotated[int, Query()],
    month: Annotated[int, Query(ge=1, le=12)],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> list[PerformanceCalendarItem]:
    return list(
        performance_service.list_performances_for_month(
            db, year, month, current_user.id
        )
    )


@performance_router.get("/available")
def get_available_data(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceAvailableData:
    return performance_service.get_available_data(db)


@performance_router.get("/{performance_id}")
def get_performance(
    performance_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_verified_user)],
) -> PerformanceShowResponse:
    return performance_service.get_performance_detail(db, performance_id)


@performance_router.get("/{performance_id}/form")
def get_performance_form_data(
    performance_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceFormData:
    return performance_service.get_form_data(db, performance_id)


@performance_router.post("", status_code=status.HTTP_201_CREATED)
def create_performance(
    data: PerformanceRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceResponse:
    return performance_service.create_performance(db, data)


@performance_router.put("/{performance_id}")
def update_performance(
    performance_id: uuid.UUID,
    data: PerformanceRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PerformanceResponse:
    return performance_service.update_performance(db, performance_id, data)


@performance_router.delete("/{performance_id}")
def delete_performance(
    performance_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    performance_service.delete_performance(db, performance_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}
