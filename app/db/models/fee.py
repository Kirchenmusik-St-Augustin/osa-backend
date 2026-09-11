import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, FetchedValue, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class Fee(Base):
    """Mirrors legacy `fees` (Phase 1 structural parity), with one
    additive DB-level hardening constraint layered on top in the
    Quick-Wins hardening slice (2026-09): `amount >= 0` is already
    enforced at the Pydantic layer (FeeRequest.amount: Field(ge=0, le=999))
    but was never backed by the database itself -- any non-API write path
    had no protection against a negative amount before this.

    A standalone billing-rate lookup table, administered through its own
    dedicated Legacy controller (`Content/System/FeeController`, not the
    generic Coreelement mechanism) -- unlike Instrument/Voice/Choirjob/
    Location/Role/Propriumelement, `fees` has no `order` column, so it
    deliberately does NOT use CoreelementColumns. Bookings copy a Fee's
    `amount` into `bookings.fee`/`booking_logs.fee` as a plain integer at
    booking time -- there is no FK from either table back to `fees.id`, so
    deleting a Fee never orphans a booking.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "fees"
    __table_args__ = (CheckConstraint("amount >= 0", name="fees_amount_check"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(unique=True)
    amount: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
