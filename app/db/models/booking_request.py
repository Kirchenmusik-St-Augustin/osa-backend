import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class BookingRequest(TimestampColumns, Base):
    """A user's open request to be booked for a Performance --
    `notbooked_at` is set once that request was explicitly rejected on the
    Cast page ("zurückweisen", the REJECTED booking status) rather than
    being fulfilled. Cleared back to NULL every time the Cast page is
    re-saved (see booking_service's `_apply_notbooked`).

    `notbooked_at` is TIMESTAMPTZ and stays Python-managed.

    `performance_id`/`user_id` foreign keys are deliberately asymmetric:
    `performance_id` is ON DELETE RESTRICT
    (performance_service._has_bookings_or_requests() already blocks deleting
    a Performance with open requests), `user_id` is ON DELETE CASCADE
    (user_service._is_deletable() explicitly does NOT block deleting a User
    for having an open, unfulfilled request -- an open request has no
    meaning without the user who made it)."""

    __tablename__ = "booking_requests"
    __table_args__ = (
        UniqueConstraint("performance_id", "user_id"),
        Index("booking_requests_user_id_index", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performances.id", ondelete="RESTRICT", onupdate="RESTRICT")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    notbooked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
