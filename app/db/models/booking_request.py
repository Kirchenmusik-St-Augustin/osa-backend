from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BookingRequest(Base):
    """Mirrors legacy `booking_requests` exactly (Phase 1). A user's open
    request to be booked for a Performance -- `notbooked_at` is set once
    that request was explicitly rejected on the Cast page ("zurückweisen",
    userBookingStatus() status 5) rather than being fulfilled. Cleared back
    to NULL every time the Cast page is re-saved (see booking_service's
    `_apply_notbooked`, a 1:1 port of `Performance::notbooked()`).

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `notbooked_at` is also TIMESTAMPTZ now (same slice)
    but stays Python-managed -- only its storage type changed."""

    __tablename__ = "booking_requests"
    __table_args__ = (UniqueConstraint("performance_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    user_id: Mapped[int]
    notbooked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
