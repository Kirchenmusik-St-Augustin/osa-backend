from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models.user_position import UserPosition
from app.services.position_types import (
    POSITION_TYPES,
    PositionType,
    position_key,
    position_kwargs,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import InstrumentedAttribute, Session

# UserPosition's own WHERE-clause dispatch table -- see booking_service.py's
# identical _BOOKING_POSITION_COLUMNS for the full rationale.
_USER_POSITION_COLUMNS: dict[PositionType, InstrumentedAttribute[uuid.UUID | None]] = {
    "instruments": UserPosition.instrument_id,
    "voices": UserPosition.voice_id,
    "choirjobs": UserPosition.choirjob_id,
}


def get_position_ids_for_user(
    db: Session, user_id: uuid.UUID
) -> dict[PositionType, set[uuid.UUID]]:
    """A User's own Instrument/Voice/Choirjob qualifications -- one query,
    used by the booking status' bookable-intersection check."""
    result: dict[PositionType, set[uuid.UUID]] = {
        position_type: set() for position_type in POSITION_TYPES
    }
    rows = db.execute(select(UserPosition).where(UserPosition.user_id == user_id))
    for user_position in rows.scalars():
        position_type, position_id = position_key(user_position)
        result[position_type].add(position_id)
    return result


def get_qualified_user_ids_batch(
    db: Session, keys: dict[PositionType, set[uuid.UUID]]
) -> dict[tuple[PositionType, uuid.UUID], set[uuid.UUID]]:
    """Which users are qualified for each (position_type, position_id) in
    `keys` -- at most one query PER TYPE (not per item), the N+1-safe
    building block for staff()'s `bookable` candidate lists."""
    result: dict[tuple[PositionType, uuid.UUID], set[uuid.UUID]] = {
        (position_type, position_id): set()
        for position_type, position_ids in keys.items()
        for position_id in position_ids
    }
    for position_type, position_ids in keys.items():
        if not position_ids:
            continue
        position_column = _USER_POSITION_COLUMNS[position_type]
        rows = db.execute(
            select(position_column, UserPosition.user_id).where(
                position_column.in_(position_ids)
            )
        ).all()
        for position_id, user_id in rows:
            # position_id is statically `uuid.UUID | None` (it's the same
            # InstrumentedAttribute used in the WHERE clause above), but
            # the `.in_(position_ids)` filter guarantees non-NULL at
            # runtime for every returned row.
            if position_id is None:
                continue
            result[(position_type, position_id)].add(user_id)
    return result


def is_bookable(
    user_position_ids: dict[PositionType, set[uuid.UUID]],
    performance_position_ids: dict[PositionType, set[uuid.UUID]],
) -> bool:
    """The bookable check of the booking status: does the user hold at least
    one Instrument/Voice/Choirjob qualification that the performance
    actually needs (a single intersection per type)."""
    return any(
        user_position_ids[position_type] & performance_position_ids[position_type]
        for position_type in POSITION_TYPES
    )


def create_user_position(
    db: Session,
    *,
    user_id: uuid.UUID,
    position_type: PositionType,
    position_id: uuid.UUID,
) -> UserPosition:
    """Seeding helper for tests and fixtures -- there is deliberately no
    router endpoint for this."""
    user_position = UserPosition(
        user_id=user_id, **position_kwargs(position_type, position_id)
    )
    db.add(user_position)
    db.commit()
    return user_position


def sync_user_positions(
    db: Session, *, user_id: uuid.UUID, desired: dict[PositionType, set[uuid.UUID]]
) -> None:
    """Replaces a User's Instrument/Voice/Choirjob assignments with exactly
    `desired` -- remove-not-in-new/insert-new. No commit
    here -- the caller (user_service.create_user/update_user) controls the
    transaction, same convention as ordinariumwork_service._sync_positions."""
    existing = (
        db.execute(select(UserPosition).where(UserPosition.user_id == user_id))
        .scalars()
        .all()
    )
    existing_by_key = {position_key(p): p for p in existing}
    existing_keys: set[tuple[PositionType, uuid.UUID]] = set(existing_by_key)
    desired_keys: set[tuple[PositionType, uuid.UUID]] = {
        (position_type, position_id)
        for position_type, position_ids in desired.items()
        for position_id in position_ids
    }

    for key, position in existing_by_key.items():
        if key not in desired_keys:
            db.delete(position)

    for position_type, position_id in desired_keys - existing_keys:
        db.add(
            UserPosition(user_id=user_id, **position_kwargs(position_type, position_id))
        )
