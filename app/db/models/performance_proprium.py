from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PerformanceProprium(Base):
    """Pivot row: which Propriumwork fills which liturgical Propriumelement
    slot (e.g. "Graduale") for a Performance. Unique per (performance,
    element) -- only one work per liturgical slot per performance.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "performance_proprium"
    __table_args__ = (UniqueConstraint("performance_id", "propriumelement_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    propriumelement_id: Mapped[int]
    propriumwork_id: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
