import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_columns_mixin import PositionColumns
from app.db.uuid_pk import uuid_pk

# Native Postgres ENUM for this table's own booking_type column (see
# alembic/versions/fa9e6613c5c1_convert_booking_type_to_enum.py). Unlike the
# former position_type column, nothing else shares this type, so it's
# declared directly here rather than in its own module -- same
# bare-string-literal reasoning as PositionColumns' own docstring (avoids
# the values_callable footgun a bound Python enum.Enum class would
# reintroduce).
booking_type_enum = Enum("book", "unbook", name="booking_type")


class BookingLog(PositionColumns, Base):
    """Mirrors legacy `booking_logs` (Phase 1 structural parity), with four
    additive DB-level hardening changes layered on top since Phase 1:
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
    - `booking_type` is a native Postgres ENUM as of the enum-hardening
      slice (2026-09), replacing the CHECK constraint it used to have --
      `Mapped[str]` is unchanged, every existing string comparison keeps
      working.
    - `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
      audit-trigger hardening slice (2026-09): `created_at` is populated
      by the database's own DEFAULT now(), `updated_at` by the shared
      set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
      Python anymore. `notified_at` is also TIMESTAMPTZ now (same slice)
      but stays Python-managed -- only its storage type changed.

    One append-only row per book/unbook transition -- deliberately NO
    unique index, duplicates are the expected shape (every promote/demote/
    cast-change produces a new row). `notified_at` is set by the scheduled
    `notify_upcoming_booking_status` job once a user has been emailed about
    this transition (see booking_jobs.py, a port of Legacy's
    `BookingLog::checkNotificationForUpcomingPerformances()`).

    `performance_id`/`user_id` are nullable, ON DELETE SET NULL foreign
    keys as of the FK-hardening slice (2026-09): a deleted Performance or
    User does not remove or block deletion of its historical booking_log
    rows -- they survive as orphaned (NULL-referencing) audit entries,
    matching this table's append-only nature.

    `position_type`/`position_id` are replaced by three mutually-exclusive
    nullable foreign keys (`instrument_id`/`voice_id`/`choirjob_id`, see
    PositionColumns) as of the polymorphy-redesign slice (2026-09).
    Deliberately ON DELETE RESTRICT here, NOT SET NULL like performance_id/
    user_id above: a SET NULL on the one populated position column would
    itself violate `booking_logs_position_exactly_one_check` the instant it
    fired (nulling the only non-null column drops the count to 0), so the
    two philosophies -- "SET NULL on parent deletion" and "exactly one of
    three must stay set" -- are structurally incompatible for the same
    column set. Since Instrument/Voice/Choirjob are never hard-deleted in
    this system anyway (see PositionColumns' own docstring), RESTRICT here
    is inert in practice, not a live behavioral gap."""

    __tablename__ = "booking_logs"
    __table_args__ = (
        CheckConstraint("fee >= 0", name="booking_logs_fee_check"),
        CheckConstraint(
            "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
            name="booking_logs_position_exactly_one_check",
        ),
        Index(
            "booking_logs_performance_id_user_id_created_at_index",
            "performance_id",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("performances.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    booking_type: Mapped[str] = mapped_column(booking_type_enum)
    fee: Mapped[int]
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
