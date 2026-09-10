from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, FetchedValue, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_type_enum import position_type_enum


class OrdinariumworkPosition(Base):
    """Pivot row: which Instrument/Voice an Ordinariumwork needs, and in
    what quantity (e.g. "2x Violine, 4x Sopran"). Legacy's `position_type`/
    `position_id` polymorphy (Relation::morphMap 'instruments'/'voices'/
    'choirjobs') is deliberately restricted to 'instruments'/'voices' ONLY
    here -- confirmed by the real CHECK constraint AND by live data (1677
    rows, zero 'choirjobs'). No standalone controller/routes in Legacy:
    managed entirely through Ordinariumwork's own create/update ("setup"
    payload), never directly -- same here (see ordinariumwork_service.py).

    `position_type` uses the shared 3-value native Postgres ENUM (see
    app.db.models.position_type_enum), the same type bookings/booking_logs/
    performance_positions/user_positions use -- but this table's own
    CHECK constraint below stays in place on top of it. The enum type
    itself can't express "2 of these 3 values" (Postgres ENUMs have no
    concept of a per-column subset), so the CHECK remains the only thing
    excluding 'choirjobs' here, exactly as it did before the enum
    conversion.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "ordinariumwork_positions"
    __table_args__ = (
        UniqueConstraint("ordinariumwork_id", "position_type", "position_id"),
        CheckConstraint("position_type IN ('instruments', 'voices')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ordinariumwork_id: Mapped[int]
    position_type: Mapped[str] = mapped_column(position_type_enum)
    position_id: Mapped[int]
    quantity: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
