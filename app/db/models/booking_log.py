from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_type_enum import position_type_enum

# Native Postgres ENUM for this table's own booking_type column (see
# alembic/versions/fa9e6613c5c1_convert_booking_type_to_enum.py). Unlike
# position_type, nothing else shares this type, so it's declared directly
# here rather than in its own module -- same bare-string-literal reasoning
# as app.db.models.position_type_enum's docstring (avoids the
# values_callable footgun a bound Python enum.Enum class would reintroduce).
booking_type_enum = Enum("book", "unbook", name="booking_type")


class BookingLog(Base):
    """Mirrors legacy `booking_logs` (Phase 1 structural parity), with
    three additive DB-level hardening changes layered on top since Phase 1:
    - `booking_logs_performance_id_user_id_created_at_index`, a composite
      index covering this append-only, unboundedly-growing table's actual
      read pattern (filter by performance_id, sometimes narrowed further
      by user_id, ordered by created_at -- see booking_jobs.py's
      notify_upcoming_booking_status/_latest_unnotified_entries).
      Previously this table had no index at all.
    - `fee >= 0`, mirroring the same constraint now on `bookings.fee`
      (never backed by the database before, despite booking_logs.fee
      always being copied from an already-validated Booking.fee at write
      time).
    - `booking_type`/`position_type` are native Postgres ENUMs as of the
      enum-hardening slice (2026-09), replacing the CHECK constraints
      they used to have -- `Mapped[str]` is unchanged, every existing
      string comparison/dict-dispatch on these columns keeps working.

    One append-only row per book/unbook transition -- deliberately NO
    unique index, duplicates are the expected shape (every promote/demote/
    cast-change produces a new row). `notified_at` is set by the scheduled
    `notify_upcoming_booking_status` job once a user has been emailed about
    this transition (see booking_jobs.py, a port of Legacy's
    `BookingLog::checkNotificationForUpcomingPerformances()`). Never cleaned
    up on Performance deletion -- Legacy has no FK/cleanup path either,
    historical log rows are meant to outlive the Performance they
    describe."""

    __tablename__ = "booking_logs"
    __table_args__ = (
        CheckConstraint("fee >= 0", name="booking_logs_fee_check"),
        Index(
            "booking_logs_performance_id_user_id_created_at_index",
            "performance_id",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    user_id: Mapped[int]
    booking_type: Mapped[str] = mapped_column(booking_type_enum)
    position_type: Mapped[str] = mapped_column(position_type_enum)
    position_id: Mapped[int]
    fee: Mapped[int]
    notified_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
