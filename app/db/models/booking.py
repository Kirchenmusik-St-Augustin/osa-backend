from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_columns_mixin import PositionColumns


class Booking(PositionColumns, Base):
    """Mirrors legacy `bookings` (Phase 1 structural parity), with five
    additive DB-level hardening changes layered on top since Phase 1:
    - `bookings_user_id_index` on `user_id` alone -- both unique
      constraints below lead with `performance_id`, so a plain
      `WHERE user_id = ...` scan (see
      get_upcoming_requests_and_bookings_for_user in booking_service.py)
      had no index to use at all before this.
    - `fee >= 0`, already enforced at the Pydantic layer
      (CastMemberInput.fee: Field(ge=0)) but never backed by the database.
    - The `order` column is `sort_order` at the DB level as of the
      Quick-Wins hardening slice (2026-09) (Postgres always requires
      `order` to be double-quoted as an identifier -- a classic footgun);
      the Python attribute/ORM-facing name stays `order` via
      mapped_column's explicit column-name argument (same alias pattern
      as SentEmail.mail_from, see sent_email.py), so every existing
      `.order`/`order=`/`order_by(Booking.order)` call site is untouched.
    - `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
      audit-trigger hardening slice (2026-09): `created_at` is populated
      by the database's own DEFAULT now(), `updated_at` by the shared
      set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
      Python anymore.
    - `performance_id`/`user_id` are ON DELETE RESTRICT foreign keys as of
      the FK-hardening slice (2026-09): performance_service.
      _has_bookings_or_requests() and user_service._is_deletable() already
      block deleting a Performance or User with existing bookings, RESTRICT
      enforces that same rule at the database level.
    - `position_type`/`position_id` (a native-enum-plus-plain-int
      polymorphic pair with no FK) are replaced by three mutually-exclusive
      nullable foreign keys (`instrument_id`/`voice_id`/`choirjob_id`, see
      PositionColumns) as of the polymorphy-redesign slice (2026-09) --
      `bookings_position_exactly_one_check` enforces exactly one is set.

    One row per user actually cast into a Performance's Instrument/Voice/
    Choirjob position, `order` is the position within that position's cast
    list (0-based array index at save time) -- `order < performance_
    positions.quantity` is what makes a booking "regular" (cast) vs.
    "standby", computed in booking_service, never stored as a column.

    Two unique constraints, both load-bearing: the five-column one is the
    obvious one-slot-per-user-per-position rule (postgresql_nulls_not_
    distinct=True, since every row has two NULLs among the three position
    columns by construction -- Postgres's default NULLS DISTINCT semantics
    would otherwise treat every such row as unique regardless of the
    populated column, silently permitting duplicate bookings); the
    two-column `(performance_id, user_id)` one is the stronger business
    rule that a user can only ever hold ONE booking per performance at all,
    regardless of position -- booking_service enforces this app-side by
    deleting any existing booking for the same user on a DIFFERENT position
    before inserting a new one (see saveCastItem's "purge other position"
    step)."""

    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint(
            "performance_id",
            "user_id",
            "instrument_id",
            "voice_id",
            "choirjob_id",
            name="bookings_position_unique",
            postgresql_nulls_not_distinct=True,
        ),
        UniqueConstraint("performance_id", "user_id"),
        CheckConstraint(
            "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
            name="bookings_position_exactly_one_check",
        ),
        CheckConstraint("fee >= 0", name="bookings_fee_check"),
        Index("bookings_user_id_index", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int] = mapped_column(
        ForeignKey("performances.id", ondelete="RESTRICT")
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    order: Mapped[int] = mapped_column("sort_order", default=0)
    fee: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
