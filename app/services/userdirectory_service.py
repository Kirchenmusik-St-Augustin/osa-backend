from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models.user import User
from app.db.models.user_position import UserPosition
from app.schemas.base import IdNameOutput
from app.schemas.coreelement import CoreelementType
from app.schemas.pagination import PagedRows
from app.schemas.userdirectory import (
    DirectoryType,
    UserDirectoryAbilitiesOutput,
    UserDirectoryEntryOutput,
)
from app.services import coreelement_service
from app.services.pagination import select_page
from app.services.position_types import position_column

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.schemas.pagination import PageParams
    from app.services.position_types import PositionType


def to_entry(user: User) -> UserDirectoryEntryOutput:
    has_email = user.email_verified_at is not None
    return UserDirectoryEntryOutput(
        id=user.id,
        surname=user.surname,
        givenname=user.givenname,
        has_email=has_email,
        email=user.email if has_email else None,
        phone=user.phone,
    )


def get_abilities(db: Session) -> UserDirectoryAbilitiesOutput:
    """Catalog for the filter dropdown -- reuses coreelement_service like
    user_service.get_form_options() does, roles excluded (see
    UserDirectoryAbilitiesOutput docstring)."""

    def _refs(type_: CoreelementType) -> list[IdNameOutput]:
        return [
            IdNameOutput(id=item.id, name=item.name)
            for item in coreelement_service.list_coreelements(db, type_)
        ]

    return UserDirectoryAbilitiesOutput(
        instruments=_refs(CoreelementType.instrument),
        voices=_refs(CoreelementType.voice),
        choirjobs=_refs(CoreelementType.choirjob),
    )


def list_all_users(db: Session, page: PageParams) -> PagedRows[User]:
    """All users (type=all) -- excludes soft-deleted users, ordered by
    surname/givenname."""
    stmt = (
        select(User)
        .where(User.deleted_at.is_(None))
        .order_by(User.surname, User.givenname, User.id)
    )
    return select_page(db, stmt, page)


def list_users_for_position(
    db: Session,
    position_type: PositionType,
    position_id: uuid.UUID,
    page: PageParams,
) -> PagedRows[User]:
    """Users holding a position (type=instruments|voices|choirjobs) -- via
    the user_positions pivot, same ordering/soft-delete exclusion as
    list_all_users(). A position_id that doesn't correspond to a real
    Instrument/Voice/Choirjob row simply yields no matches (the filter
    dropdown only ever offers ids it fetched from get_abilities() itself,
    so this path is not reachable through the real UI -- no need for a 404
    here)."""
    stmt = (
        select(User)
        .join(UserPosition, UserPosition.user_id == User.id)
        .where(
            position_column(UserPosition, position_type) == position_id,
            User.deleted_at.is_(None),
        )
        .order_by(User.surname, User.givenname, User.id)
    )
    return select_page(db, stmt, page)


def list_entries(
    db: Session,
    directory_type: DirectoryType | None,
    position_id: uuid.UUID | None,
    page: PageParams,
) -> PagedRows[UserDirectoryEntryOutput]:
    """One page of the directory: everybody for no type or type=all, the
    holders of one position for a position type together with its id, and
    nobody for a position type without an id."""
    if directory_type is None or directory_type == "all":
        users = list_all_users(db, page)
    elif position_id is not None:
        users = list_users_for_position(db, directory_type, position_id, page)
    else:
        users = PagedRows[User](rows=[], total=0)
    return users.map(to_entry)
