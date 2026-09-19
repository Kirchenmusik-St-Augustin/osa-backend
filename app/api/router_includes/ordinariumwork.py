import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.ordinariumwork import (
    OrdinariumworkAvailablePositionsOutput,
    OrdinariumworkRequest,
    OrdinariumworkResponse,
    OrdinariumworkSearchResult,
    OrdinariumworkSetupOutput,
)
from app.services import ordinariumwork_service

ordinariumwork_router = APIRouter()

_MAINTAIN = Depends(require_permission("ordinariumworkMaintain"))


@ordinariumwork_router.get("/search")
def search_ordinariumworks(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[OrdinariumworkSearchResult]:
    return list(ordinariumwork_service.search_ordinariumworks(db, q))


@ordinariumwork_router.post("", status_code=status.HTTP_201_CREATED)
def create_ordinariumwork(
    data: OrdinariumworkRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkResponse:
    return ordinariumwork_service.create_ordinariumwork(db, data)


@ordinariumwork_router.get("/available-positions")
def get_available_positions(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkAvailablePositionsOutput:
    return ordinariumwork_service.get_available_positions(db)


@ordinariumwork_router.get("/{ordinariumwork_id}")
def get_ordinariumwork(
    ordinariumwork_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkResponse:
    return ordinariumwork_service.get_ordinariumwork(db, ordinariumwork_id)


@ordinariumwork_router.get("/{ordinariumwork_id}/setup")
def get_ordinariumwork_setup(
    ordinariumwork_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkSetupOutput:
    return ordinariumwork_service.get_setup(db, ordinariumwork_id)


@ordinariumwork_router.put("/{ordinariumwork_id}")
def update_ordinariumwork(
    ordinariumwork_id: uuid.UUID,
    data: OrdinariumworkRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkResponse:
    return ordinariumwork_service.update_ordinariumwork(db, ordinariumwork_id, data)


@ordinariumwork_router.delete("/{ordinariumwork_id}")
def delete_ordinariumwork(
    ordinariumwork_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    ordinariumwork_service.delete_ordinariumwork(db, ordinariumwork_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}
