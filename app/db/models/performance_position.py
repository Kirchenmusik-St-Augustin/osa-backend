from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_type_enum import position_type_enum


class PerformancePosition(Base):
    """Pivot row: which Instrument/Voice/Choirjob a Performance needs, and
    in what quantity. Unlike OrdinariumworkPosition, Performance's
    position_type polymorphy legitimately includes ALL THREE types --
    confirmed live: Legacy's Performance uses instruments/voices/choirjobs,
    only Ordinariumwork's CHECK constraint excludes choirjobs.
    `position_type` is the shared native Postgres ENUM (see
    app.db.models.position_type_enum) as of the enum-hardening slice
    (2026-09), replacing its former CHECK constraint.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "performance_positions"
    __table_args__ = (
        UniqueConstraint("performance_id", "position_type", "position_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    position_type: Mapped[str] = mapped_column(position_type_enum)
    position_id: Mapped[int]
    quantity: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
