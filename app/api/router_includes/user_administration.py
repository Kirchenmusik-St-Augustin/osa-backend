from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.user_administration import (
    UserAdministrationActionResponse,
    UserAdministrationDeletedEntryOutput,
    UserAdministrationDetailOutput,
    UserAdministrationSearchResultOutput,
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


def _to_detail(user: User) -> UserAdministrationDetailOutput:
    return UserAdministrationDetailOutput(
        id=user.id,
        surname=user.surname,
        givenname=user.givenname,
        email=user.email,
        email_verified_at=user.email_verified_at,
        auth_locked=user.auth_locked,
        deleted_at=user.deleted_at,
        auth_lastsignal=user.auth_lastsignal,
    )


@user_administration_router.get("/search")
def search_users(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _ADMINISTRATE],
) -> list[UserAdministrationSearchResultOutput]:
    users = user_administration_service.search_users_including_deleted(db, q)
    return [
        UserAdministrationSearchResultOutput(
            id=user.id, label=f"{user.surname}, {user.givenname}"
        )
        for user in users
    ]


@user_administration_router.get("/deleted")
def list_deleted_users(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _ADMINISTRATE],
) -> list[UserAdministrationDeletedEntryOutput]:
    users = user_administration_service.list_deleted_users(db)
    return [
        UserAdministrationDeletedEntryOutput(
            id=user.id, surname=user.surname, givenname=user.givenname, email=user.email
        )
        for user in users
    ]


@user_administration_router.get("/{user_id}")
def get_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _ADMINISTRATE],
) -> UserAdministrationActionResponse:
    try:
        user = user_administration_service.get_user(db, user_id)
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return UserAdministrationActionResponse(user=_to_detail(user))


@user_administration_router.post("/{user_id}/restore")
def restore_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _ADMINISTRATE],
) -> UserAdministrationActionResponse:
    try:
        user = user_administration_service.restore_user(db, user_id)
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return UserAdministrationActionResponse(user=_to_detail(user))


@user_administration_router.post("/{user_id}/unlock")
def unlock_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _ADMINISTRATE],
) -> UserAdministrationActionResponse:
    try:
        user = user_administration_service.unlock_user(db, user_id)
    except UserAdministrationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return UserAdministrationActionResponse(user=_to_detail(user))


@user_administration_router.post("/{user_id}/set-password")
def set_password(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _ADMINISTRATE],
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
    return UserAdministrationActionResponse(user=_to_detail(user), newpw=plain_password)
