from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models.user import User
from app.db.models.user_position import UserPosition
from app.schemas.coreelement import CoreelementType
from app.schemas.performance import PositionRefOutput
from app.schemas.userdirectory import UserDirectoryAbilitiesOutput
from app.services import coreelement_service

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import InstrumentedAttribute, Session

    from app.services.position_types import PositionType

# UserPosition's own WHERE-clause dispatch table -- see booking_service.py's
# identical _BOOKING_POSITION_COLUMNS for the full rationale.
_USER_POSITION_COLUMNS: dict[PositionType, InstrumentedAttribute[uuid.UUID | None]] = {
    "instruments": UserPosition.instrument_id,
    "voices": UserPosition.voice_id,
    "choirjobs": UserPosition.choirjob_id,
}


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
    """All users (type=all) -- excludes soft-deleted users, ordered by
    surname/givenname."""
    stmt = (
        select(User)
        .where(User.deleted_at.is_(None))
        .order_by(User.surname, User.givenname)
    )
    return db.execute(stmt).scalars().all()


def list_users_for_position(
    db: Session, position_type: PositionType, position_id: uuid.UUID
) -> Sequence[User]:
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
            _USER_POSITION_COLUMNS[position_type] == position_id,
            User.deleted_at.is_(None),
        )
        .order_by(User.surname, User.givenname)
    )
    return db.execute(stmt).scalars().all()
