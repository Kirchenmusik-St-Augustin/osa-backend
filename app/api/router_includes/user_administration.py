import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, require_permission
from app.api.query_params import PageDep, SearchTerm
from app.db.database import get_db
from app.schemas.base import IdLabelOutput
from app.schemas.pagination import Page
from app.schemas.user_administration import (
    UserAdministrationActionResponse,
    UserAdministrationDeletedEntryOutput,
)
from app.services import user_administration_service
from app.services.user_administration_service import (
    SelfTargetError,
    UserAdministrationNotFoundError,
)

user_administration_router = APIRouter()

_ADMINISTRATE = Depends(require_permission("userAdministrate"))
_NOT_FOUND_DETAIL = "Nicht gefunden."
_SELF_TARGET_DETAIL = "Diese Aktion ist für das eigene Konto nicht verfügbar."

# "/search" and "/deleted" must be registered before "/{user_id}" -- see
# app/api/router_includes/user.py's identical comment.


@user_administration_router.get("/search")
def search_users(
    q: SearchTerm,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _ADMINISTRATE],
) -> list[IdLabelOutput]:
    users = user_administration_service.search_users_including_deleted(db, q)
    return [user_administration_service.to_search_result(user) for user in users]


@user_administration_router.get("/deleted")
def list_deleted_users(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _ADMINISTRATE],
    page: PageDep,
) -> Page[UserAdministrationDeletedEntryOutput]:
    paged = user_administration_service.list_deleted_users(db, page)
    return Page.of(paged.map(user_administration_service.to_deleted_entry), page)


@user_administration_router.get("/{user_id}")
def get_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _ADMINISTRATE],
) -> UserAdministrationActionResponse:
    try:
        user = user_administration_service.get_user(db, user_id)
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return UserAdministrationActionResponse(
        user=user_administration_service.to_detail(db, user)
    )


@user_administration_router.post("/{user_id}/restore")
def restore_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _ADMINISTRATE],
) -> UserAdministrationActionResponse:
    try:
        user = user_administration_service.restore_user(db, user_id)
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return UserAdministrationActionResponse(
        user=user_administration_service.to_detail(db, user)
    )


@user_administration_router.post("/{user_id}/unlock")
def unlock_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _ADMINISTRATE],
) -> UserAdministrationActionResponse:
    try:
        user = user_administration_service.unlock_user(db, user_id)
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return UserAdministrationActionResponse(
        user=user_administration_service.to_detail(db, user)
    )


@user_administration_router.post("/{user_id}/set-password")
def set_password(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthUser, _ADMINISTRATE],
) -> UserAdministrationActionResponse:
    try:
        user, plain_password = user_administration_service.set_random_password(
            db, user_id, current_user.id
        )
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except SelfTargetError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=_SELF_TARGET_DETAIL
        ) from None
    return UserAdministrationActionResponse(
        user=user_administration_service.to_detail(db, user), newpw=plain_password
    )


@user_administration_router.delete("/{user_id}")
def purge_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _ADMINISTRATE],
) -> dict[str, str]:
    try:
        user_administration_service.purge_user(db, user_id)
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return {"status": "ok", "message": "Benutzerkonto wurde dauerhaft gelöscht."}
