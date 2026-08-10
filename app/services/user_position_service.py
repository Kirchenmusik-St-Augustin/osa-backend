from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.user_position import UserPosition
from app.services.position_types import POSITION_TYPES, PositionType


def get_position_ids_for_user(
    db: Session, user_id: int
) -> dict[PositionType, set[int]]:
    """A User's own Instrument/Voice/Choirjob qualifications -- one query,
    used by userBookingStatus()'s bookable-intersection check."""
    result: dict[PositionType, set[int]] = {
        position_type: set() for position_type in POSITION_TYPES
    }
    rows = db.execute(
        select(UserPosition.position_type, UserPosition.position_id).where(
            UserPosition.user_id == user_id
        )
    ).all()
    for position_type, position_id in rows:
        result[position_type].add(position_id)
    return result


def get_qualified_user_ids_batch(
    db: Session, keys: dict[PositionType, set[int]]
) -> dict[tuple[PositionType, int], set[int]]:
    """Which users are qualified for each (position_type, position_id) in
    `keys` -- at most one query PER TYPE (not per item), the N+1-safe
    building block for staff()'s `bookable` candidate lists."""
    result: dict[tuple[PositionType, int], set[int]] = {
        (position_type, position_id): set()
        for position_type, position_ids in keys.items()
        for position_id in position_ids
    }
    for position_type, position_ids in keys.items():
        if not position_ids:
            continue
        rows = db.execute(
            select(UserPosition.position_id, UserPosition.user_id).where(
                UserPosition.position_type == position_type,
                UserPosition.position_id.in_(position_ids),
            )
        ).all()
        for position_id, user_id in rows:
            result[(position_type, position_id)].add(user_id)
    return result


def is_bookable(
    user_position_ids: dict[PositionType, set[int]],
    performance_position_ids: dict[PositionType, set[int]],
) -> bool:
    """Port of `userBookingStatus()`'s bookable check: does the user hold at
    least one Instrument/Voice/Choirjob qualification that the performance
    actually needs. Legacy runs a redundant, commutative
    `array_intersect($a,$b) || array_intersect($b,$a)` check per type --
    that duplication is not replicated here, a single intersection per type
    is equivalent (see project_osa_migration_plan memory, Schritt 6 plan)."""
    return any(
        user_position_ids[position_type] & performance_position_ids[position_type]
        for position_type in POSITION_TYPES
    )


def create_user_position(
    db: Session, *, user_id: int, position_type: PositionType, position_id: int
) -> UserPosition:
    """Dev/test/fixture-seeding helper -- there is deliberately no router
    endpoint for this in Schritt 6, the admin UI to assign these lands with
    Schritt 7 (User-/System-Verwaltung)."""
    now = datetime.now(UTC)
    user_position = UserPosition(
        user_id=user_id,
        position_type=position_type,
        position_id=position_id,
        created_at=now,
        updated_at=now,
    )
    db.add(user_position)
    db.commit()
    return user_position


def sync_user_positions(
    db: Session, *, user_id: int, desired: dict[PositionType, set[int]]
) -> None:
    """Schritt 7: replaces a User's Instrument/Voice/Choirjob assignments
    with exactly `desired` -- remove-not-in-new/insert-new, 1:1 Legacy's
    `$user->instruments()->sync(...)`/`->voices()->sync(...)`/
    `->choirjobs()->sync(...)` (System::UserController::save()). No commit
    here -- the caller (user_service.create_user/update_user) controls the
    transaction, same convention as ordinariumwork_service._sync_positions."""
    existing = (
        db.execute(select(UserPosition).where(UserPosition.user_id == user_id))
        .scalars()
        .all()
    )
    existing_keys = {(p.position_type, p.position_id) for p in existing}
    desired_keys = {
        (position_type, position_id)
        for position_type, position_ids in desired.items()
        for position_id in position_ids
    }

    for position in existing:
        if (position.position_type, position.position_id) not in desired_keys:
            db.delete(position)

    now = datetime.now(UTC)
    for position_type, position_id in desired_keys - existing_keys:
        db.add(
            UserPosition(
                user_id=user_id,
                position_type=position_type,
                position_id=position_id,
                created_at=now,
                updated_at=now,
            )
        )
