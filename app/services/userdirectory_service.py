from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user import User
from app.db.models.user_position import UserPosition
from app.schemas.coreelement import CoreelementType
from app.schemas.performance import PositionRefOutput
from app.schemas.userdirectory import UserDirectoryAbilitiesOutput
from app.services import coreelement_service
from app.services.position_types import PositionType


def get_abilities(db: Session) -> UserDirectoryAbilitiesOutput:
    """Catalog for the filter dropdown -- reuses coreelement_service like
    user_service.get_form_options() does, roles excluded (see
    UserDirectoryAbilitiesOutput docstring)."""

    def _refs(type_: CoreelementType) -> list[PositionRefOutput]:
        return [
            PositionRefOutput(id=item.id, name=item.name)
            for item in coreelement_service.list_coreelements(db, type_)
        ]

    return UserDirectoryAbilitiesOutput(
        instruments=_refs(CoreelementType.instrument),
        voices=_refs(CoreelementType.voice),
        choirjobs=_refs(CoreelementType.choirjob),
    )


def list_all_users(db: Session) -> Sequence[User]:
    """1:1 Legacy's `User::all()` branch (type=all) -- excludes soft-deleted
    users (Legacy's SoftDeletingScope applies implicitly there too),
    ordered by surname/givenname (Legacy's OrderBySurnameGivenname
    scope)."""
    stmt = (
        select(User)
        .where(User.deleted_at.is_(None))
        .order_by(User.surname, User.givenname)
    )
    return db.execute(stmt).scalars().all()


def list_users_for_position(
    db: Session, position_type: PositionType, position_id: int
) -> Sequence[User]:
    """1:1 Legacy's `$item->users` branch (type=instruments|voices|choirjobs)
    -- via the polymorphic user_positions pivot, same ordering/soft-delete
    exclusion as list_all_users(). A position_id that doesn't correspond to
    a real Instrument/Voice/Choirjob row simply yields no matches (the
    filter dropdown only ever offers ids it fetched from get_abilities()
    itself, so this path is not reachable through the real UI -- no need
    for Legacy's `findOrFail()` 404 here)."""
    stmt = (
        select(User)
        .join(UserPosition, UserPosition.user_id == User.id)
        .where(
            UserPosition.position_type == position_type,
            UserPosition.position_id == position_id,
            User.deleted_at.is_(None),
        )
        .order_by(User.surname, User.givenname)
    )
    return db.execute(stmt).scalars().all()
