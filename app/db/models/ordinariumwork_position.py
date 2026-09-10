from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class OrdinariumworkPosition(Base):
    """Pivot row: which Instrument/Voice an Ordinariumwork needs, and in
    what quantity (e.g. "2x Violine, 4x Sopran"). Legacy's `position_type`/
    `position_id` polymorphy (Relation::morphMap 'instruments'/'voices'/
    'choirjobs') is deliberately restricted to 'instruments'/'voices' ONLY
    here -- confirmed by the real CHECK constraint AND by live data (1677
    rows, zero 'choirjobs'). No standalone controller/routes in Legacy:
    managed entirely through Ordinariumwork's own create/update ("setup"
    payload), never directly -- same here (see ordinariumwork_service.py).

    As of the polymorphy-redesign slice (2026-09), `position_type`/
    `position_id` are replaced by two mutually-exclusive nullable foreign
    keys, `instrument_id`/`voice_id` -- deliberately NOT the shared
    PositionColumns mixin (see app.db.models.position_columns_mixin), which
    also carries a `choirjob_id` column: this table's exclusion of
    choirjobs is now structural (the column doesn't exist at all) rather
    than CHECK-based, strictly stronger than the old
    `position_type IN ('instruments', 'voices')` CHECK it replaces.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `ordinariumwork_id` is an ON DELETE CASCADE foreign key
    as of the FK-hardening slice (2026-09): ordinariumwork_service.
    delete_ordinariumwork() already deletes this table's own rows before
    deleting their Ordinariumwork, CASCADE moves that cleanup to the
    database."""

    __tablename__ = "ordinariumwork_positions"
    __table_args__ = (
        UniqueConstraint(
            "ordinariumwork_id",
            "instrument_id",
            "voice_id",
            name="ordinariumwork_positions_position_unique",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "num_nonnulls(instrument_id, voice_id) = 1",
            name="ordinariumwork_positions_position_exactly_one_check",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ordinariumwork_id: Mapped[int] = mapped_column(
        ForeignKey("ordinariumworks.id", ondelete="CASCADE")
    )
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    voice_id: Mapped[int | None] = mapped_column(
        ForeignKey("voices.id", ondelete="RESTRICT")
    )
    quantity: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
