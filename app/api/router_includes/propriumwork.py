import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.propriumwork import (
    PropriumworkRequest,
    PropriumworkResponse,
    PropriumworkSearchResult,
)
from app.services import propriumwork_service

propriumwork_router = APIRouter()

_MAINTAIN = Depends(require_permission("propriumworkMaintain"))


@propriumwork_router.get("/search")
def search_propriumworks(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[PropriumworkSearchResult]:
    return list(propriumwork_service.search_propriumworks(db, q))


@propriumwork_router.post("", status_code=status.HTTP_201_CREATED)
def create_propriumwork(
    data: PropriumworkRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PropriumworkResponse:
    return propriumwork_service.create_propriumwork(db, data)


@propriumwork_router.get("/{propriumwork_id}")
def get_propriumwork(
    propriumwork_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PropriumworkResponse:
    return propriumwork_service.get_propriumwork(db, propriumwork_id)


@propriumwork_router.put("/{propriumwork_id}")
def update_propriumwork(
    propriumwork_id: uuid.UUID,
    data: PropriumworkRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PropriumworkResponse:
    return propriumwork_service.update_propriumwork(db, propriumwork_id, data)


@propriumwork_router.delete("/{propriumwork_id}")
def delete_propriumwork(
    propriumwork_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    propriumwork_service.delete_propriumwork(db, propriumwork_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}
