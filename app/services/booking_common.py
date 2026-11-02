from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.datetime_utils import local_now
from app.core.human_names import label_for_name
from app.db.models.performance import Performance
from app.db.models.performance_position import PerformancePosition
from app.db.models.user import User
from app.schemas.booking import PerformanceShortOutput
from app.services.performance_service import (
    PerformanceInPastError,
    PerformanceNotFoundError,
)
from app.services.position_types import POSITION_MODELS, PositionType, position_key

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.schemas.performance import (
        BookingStatusOutput,
        PerformanceSetupOutput,
        PerformanceShowResponse,
    )


def get_performance_or_404(
    db: Session, performance_id: uuid.UUID, *, lock: bool = False
) -> Performance:
    """`lock=True` takes a row lock that lasts until the transaction ends:
    the writers of one performance's cast (planner saves, cancellations,
    setup changes) then run one after the other instead of recomputing
    promotions and log entries from a read the other has already made stale.
    Readers are not blocked."""
    stmt = select(Performance).where(Performance.id == performance_id)
    if lock:
        stmt = stmt.with_for_update()
    performance = db.execute(stmt).scalar_one_or_none()
    if performance is None:
        raise PerformanceNotFoundError
    return performance


def ensure_not_past(performance: Performance) -> None:
    if performance.schedule < local_now():
        raise PerformanceInPastError


def setup_position_ids(
    setup: PerformanceSetupOutput,
) -> dict[PositionType, set[uuid.UUID]]:
    return {
        "instruments": {item.id for item in setup.instruments},
        "voices": {item.id for item in setup.voices},
        "choirjobs": {item.id for item in setup.choirjobs},
    }


def load_users_by_id(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    """Includes soft-deleted users -- for displaying an EXISTING booking's/
    request's user, which must never crash on a deactivated account."""
    if not user_ids:
        return {}
    rows = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    return {user.id: user for user in rows}


def load_active_users_by_id(
    db: Session, user_ids: set[uuid.UUID]
) -> dict[uuid.UUID, User]:
    """Excludes soft-deleted users -- for NEW-booking candidate/suggestion
    lists (bookable candidates, popular bookings, the not-booked list)."""
    if not user_ids:
        return {}
    rows = (
        db.execute(select(User).where(User.id.in_(user_ids), User.deleted_at.is_(None)))
        .scalars()
        .all()
    )
    return {user.id: user for user in rows}


def display_name(user: User | None) -> str:
    if user is None:
        return "N. N."
    return label_for_name(user.surname, user.givenname)


def position_names_batch(
    db: Session, keys: set[tuple[PositionType, uuid.UUID]]
) -> dict[tuple[PositionType, uuid.UUID], str]:
    result: dict[tuple[PositionType, uuid.UUID], str] = {}
    ids_by_type: dict[PositionType, set[uuid.UUID]] = {}
    for position_type, position_id in keys:
        ids_by_type.setdefault(position_type, set()).add(position_id)
    for position_type, ids in ids_by_type.items():
        model = POSITION_MODELS[position_type]
        rows = db.execute(select(model.id, model.name).where(model.id.in_(ids))).all()
        for item_id, name in rows:
            result[(position_type, item_id)] = name
    return result


def quantities_for_performance(
    db: Session, performance_id: uuid.UUID
) -> dict[tuple[PositionType, uuid.UUID], int]:
    rows = (
        db.execute(
            select(PerformancePosition).where(
                PerformancePosition.performance_id == performance_id
            )
        )
        .scalars()
        .all()
    )
    return {position_key(row): row.quantity for row in rows}


def to_short_output(
    detail: PerformanceShowResponse, user_booking: BookingStatusOutput
) -> PerformanceShortOutput:
    return PerformanceShortOutput(
        id=detail.id,
        ordinariumwork_name=detail.ordinariumwork_name,
        ordinariumwork_artist_name=detail.ordinariumwork_artist_name,
        artist_name=detail.artist_name,
        schedule=detail.schedule,
        location=detail.location,
        user_booking=user_booking,
        proprium=detail.proprium,
        demanding_proprium=detail.demanding_proprium,
        rehearsals=detail.rehearsals,
    )
