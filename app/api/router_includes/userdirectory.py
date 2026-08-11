from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.userdirectory import (
    UserDirectoryAbilitiesOutput,
    UserDirectoryEntryOutput,
)
from app.services import userdirectory_service

userdirectory_router = APIRouter()

_MAINTAIN = Depends(require_permission("userMaintain"))

DirectoryType = Literal["all", "instruments", "voices", "choirjobs"]


def _to_entry(user: User) -> UserDirectoryEntryOutput:
    has_email = user.email_verified_at is not None
    return UserDirectoryEntryOutput(
        id=user.id,
        surname=user.surname,
        givenname=user.givenname,
        has_email=has_email,
        email=user.email if has_email else None,
        phone=user.phone,
    )


@userdirectory_router.get("/abilities")
def get_abilities(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> UserDirectoryAbilitiesOutput:
    return userdirectory_service.get_abilities(db)


@userdirectory_router.get("")
def list_users(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
    directory_type: Annotated[DirectoryType | None, Query(alias="type")] = None,
    position_id: Annotated[int | None, Query(alias="id")] = None,
) -> list[UserDirectoryEntryOutput]:
    if directory_type is None or directory_type == "all":
        users = userdirectory_service.list_all_users(db)
    elif position_id is not None:
        users = userdirectory_service.list_users_for_position(
            db, directory_type, position_id
        )
    else:
        users = []
    return [_to_entry(user) for user in users]
