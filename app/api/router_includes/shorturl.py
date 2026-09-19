import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.shorturl import ShorturlListResponse, ShorturlRequest, ShorturlResponse
from app.services import shorturl_service

shorturl_router = APIRouter()

_MAINTAIN = Depends(require_permission("shorturlMaintain"))


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
    return shorturl_service.create_shorturl(db, data)


@shorturl_router.put("/{shorturl_id}")
def update_shorturl(
    shorturl_id: uuid.UUID,
    data: ShorturlRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> ShorturlResponse:
    return shorturl_service.update_shorturl(db, shorturl_id, data)


@shorturl_router.delete("/{shorturl_id}")
def delete_shorturl(
    shorturl_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    shorturl_service.delete_shorturl(db, shorturl_id)
    return {"status": "ok", "message": "Element wurde gelöscht."}
