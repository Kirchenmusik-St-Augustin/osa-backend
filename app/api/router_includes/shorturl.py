from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.shorturl import ShorturlListResponse, ShorturlRequest, ShorturlResponse
from app.services import shorturl_service
from app.services.shorturl_service import ShorturlNotFoundError, ShorturlValidationError

shorturl_router = APIRouter()

_MAINTAIN = Depends(require_permission("shorturlMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."


@shorturl_router.get("")
def list_shorturls(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ShorturlListResponse:
    return shorturl_service.list_shorturls_with_prefix(db)


@shorturl_router.post("", status_code=status.HTTP_201_CREATED)
def create_shorturl(
    data: ShorturlRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ShorturlResponse:
    try:
        return shorturl_service.create_shorturl(db, data)
    except ShorturlValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@shorturl_router.put("/{shorturl_id}")
def update_shorturl(
    shorturl_id: int,
    data: ShorturlRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ShorturlResponse:
    try:
        return shorturl_service.update_shorturl(db, shorturl_id, data)
    except ShorturlNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except ShorturlValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@shorturl_router.delete("/{shorturl_id}")
def delete_shorturl(
    shorturl_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    try:
        shorturl_service.delete_shorturl(db, shorturl_id)
    except ShorturlNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return {"status": "ok", "message": "Element wurde gelöscht."}
