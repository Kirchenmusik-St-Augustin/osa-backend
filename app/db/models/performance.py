import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, FetchedValue, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class Performance(Base):
    """Mirrors legacy `performances` (Phase 1 structural parity), with
    five additive DB-level hardening changes layered on top in the
    Quick-Wins hardening slice (2026-09):
    - `performances_schedule_index` on `schedule` -- filtered/sorted on in
      performance_service.py, booking_jobs.py, booking_service.py, and
      user_service.py, with no index to support any of it before this.
    - Four money CheckConstraints (`choirjob_defaultfee >= 0`,
      `instrument_defaultfee >= 0`, `voice_defaultfee >= 0`, and
      `extracost_amount IS NULL OR extracost_amount >= 0` -- NULLABLE, so
      the constraint must keep allowing NULL), each already enforced at
      the Pydantic layer (PerformanceRequest's `Field(ge=0)`s) but never
      backed by the database before this.

    `artist_id` here is the CONDUCTOR (Dirigent), not a composer -- a
    separate, nullable reference into the same `artists` table used by
    Ordinariumwork/Propriumwork's composer `artist_id`. `location_id`/
    `ordinariumwork_id`/`artist_id` are ON DELETE RESTRICT foreign keys as
    of the FK-hardening slice (2026-09): coreelement_service.
    _location_has_dependent_performances(), ordinariumwork_service.
    _ordinariumwork_has_dependencies(), and artist_service.
    _artist_has_dependencies() already block deleting any of the three
    while referenced here. `choirjob_defaultfee`/`instrument_defaultfee`/
    `voice_defaultfee` are NOT the fee actually paid to a booked musician
    (chosen per-booking on the Cast page, Schritt 6) -- they're
    placeholder billing rates used only to price still-unfilled slots in
    the Abrechnung.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `schedule` deliberately stays a naive TIMESTAMP: it's
    user-entered local wall-clock time in Settings.app_timezone, not a
    UTC instant (see app.core.datetime_utils module docstring)."""

    __tablename__ = "performances"
    __table_args__ = (
        CheckConstraint(
            "choirjob_defaultfee >= 0", name="performances_choirjob_defaultfee_check"
        ),
        CheckConstraint(
            "instrument_defaultfee >= 0",
            name="performances_instrument_defaultfee_check",
        ),
        CheckConstraint(
            "voice_defaultfee >= 0", name="performances_voice_defaultfee_check"
        ),
        CheckConstraint(
            "extracost_amount IS NULL OR extracost_amount >= 0",
            name="performances_extracost_amount_check",
        ),
        Index("performances_schedule_index", "schedule"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    schedule: Mapped[datetime] = mapped_column(DateTime())
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    ordinariumwork_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ordinariumworks.id", ondelete="RESTRICT")
    )
    artist_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artists.id", ondelete="RESTRICT")
    )
    description: Mapped[str | None]
    choirjob_defaultfee: Mapped[int] = mapped_column(default=35)
    instrument_defaultfee: Mapped[int] = mapped_column(default=60)
    voice_defaultfee: Mapped[int] = mapped_column(default=110)
    extracost_amount: Mapped[int | None]
    extracost_description: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
