"""Seeds a user's Instrument/Voice/Choirjob qualification directly, since no
endpoint creates a single one (the user form replaces the whole set)."""

from typing import TYPE_CHECKING

from app.db.models.user_position import UserPosition
from app.services.position_types import PositionType, position_kwargs

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


def create_user_position(
    db: Session,
    *,
    user_id: uuid.UUID,
    position_type: PositionType,
    position_id: uuid.UUID,
) -> UserPosition:
    user_position = UserPosition(
        user_id=user_id, **position_kwargs(position_type, position_id)
    )
    db.add(user_position)
    db.commit()
    return user_position
