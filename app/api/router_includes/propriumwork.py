from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.propriumwork import (
    PropriumworkRequest,
    PropriumworkResponse,
    PropriumworkSearchResult,
)
from app.services import propriumwork_service
from app.services.propriumwork_service import (
    PropriumworkNotFoundError,
    PropriumworkValidationError,
)

propriumwork_router = APIRouter()

_MAINTAIN = Depends(require_permission("propriumworkMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."


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
    try:
        return propriumwork_service.create_propriumwork(db, data)
    except PropriumworkValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@propriumwork_router.get("/{propriumwork_id}")
def get_propriumwork(
    propriumwork_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PropriumworkResponse:
    try:
        return propriumwork_service.get_propriumwork(db, propriumwork_id)
    except PropriumworkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None


@propriumwork_router.put("/{propriumwork_id}")
def update_propriumwork(
    propriumwork_id: int,
    data: PropriumworkRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> PropriumworkResponse:
    try:
        return propriumwork_service.update_propriumwork(db, propriumwork_id, data)
    except PropriumworkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except PropriumworkValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@propriumwork_router.delete("/{propriumwork_id}")
def delete_propriumwork(
    propriumwork_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    try:
        propriumwork_service.delete_propriumwork(db, propriumwork_id)
    except PropriumworkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return {"status": "ok", "message": "Element wurde gelöscht."}
