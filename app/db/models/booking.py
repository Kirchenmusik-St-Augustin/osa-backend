from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Booking(Base):
    """Mirrors legacy `bookings` exactly (Phase 1). One row per user
    actually cast into a Performance's Instrument/Voice/Choirjob position,
    `order` is the position within that position's cast list (0-based array
    index at save time) -- `order < performance_positions.quantity` is what
    makes a booking "regular" (cast) vs. "standby", computed in
    booking_service, never stored as a column (see
    project_osa_performance_domain_research memory).

    Two unique constraints, both load-bearing: the four-column one is the
    obvious one-slot-per-user-per-position rule; the two-column
    `(performance_id, user_id)` one is the stronger business rule that a
    user can only ever hold ONE booking per performance at all, regardless
    of position -- booking_service enforces this app-side by deleting any
    existing booking for the same user on a DIFFERENT position before
    inserting a new one (see saveCastItem's "purge other position" step)."""

    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("performance_id", "user_id", "position_type", "position_id"),
        UniqueConstraint("performance_id", "user_id"),
        CheckConstraint("position_type IN ('instruments', 'voices', 'choirjobs')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    user_id: Mapped[int]
    position_type: Mapped[str]
    position_id: Mapped[int]
    order: Mapped[int] = mapped_column(default=0)
    fee: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
