from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.error_responses import field_errors_to_detail
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
from app.services.ordinariumwork_service import (
    OrdinariumworkInUseError,
    OrdinariumworkNotFoundError,
    OrdinariumworkValidationError,
)

ordinariumwork_router = APIRouter()

_MAINTAIN = Depends(require_permission("ordinariumworkMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."
_IN_USE_DETAIL = "Das Element kann nicht gelöscht werden, da es noch in Verwendung ist."


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
    try:
        return ordinariumwork_service.create_ordinariumwork(db, data)
    except OrdinariumworkValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@ordinariumwork_router.get("/available-positions")
def get_available_positions(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkAvailablePositionsOutput:
    return ordinariumwork_service.get_available_positions(db)


@ordinariumwork_router.get("/{ordinariumwork_id}")
def get_ordinariumwork(
    ordinariumwork_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkResponse:
    try:
        return ordinariumwork_service.get_ordinariumwork(db, ordinariumwork_id)
    except OrdinariumworkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None


@ordinariumwork_router.get("/{ordinariumwork_id}/setup")
def get_ordinariumwork_setup(
    ordinariumwork_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkSetupOutput:
    try:
        return ordinariumwork_service.get_setup(db, ordinariumwork_id)
    except OrdinariumworkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None


@ordinariumwork_router.put("/{ordinariumwork_id}")
def update_ordinariumwork(
    ordinariumwork_id: int,
    data: OrdinariumworkRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> OrdinariumworkResponse:
    try:
        return ordinariumwork_service.update_ordinariumwork(db, ordinariumwork_id, data)
    except OrdinariumworkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except OrdinariumworkValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@ordinariumwork_router.delete("/{ordinariumwork_id}")
def delete_ordinariumwork(
    ordinariumwork_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    try:
        ordinariumwork_service.delete_ordinariumwork(db, ordinariumwork_id)
    except OrdinariumworkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except OrdinariumworkInUseError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail([("general", _IN_USE_DETAIL)]),
        ) from None
    return {"status": "ok", "message": "Element wurde gelöscht."}
