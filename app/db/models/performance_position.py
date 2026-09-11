import uuid
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
from app.db.models.position_columns_mixin import PositionColumns
from app.db.uuid_pk import uuid_pk


class PerformancePosition(PositionColumns, Base):
    """Pivot row: which Instrument/Voice/Choirjob a Performance needs, and
    in what quantity. Unlike OrdinariumworkPosition, Performance's position
    polymorphy legitimately includes ALL THREE types -- confirmed live:
    Legacy's Performance uses instruments/voices/choirjobs, only
    Ordinariumwork excludes choirjobs.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `performance_id` is an ON DELETE CASCADE foreign key as
    of the FK-hardening slice (2026-09): performance_service.
    delete_performance() already deletes this table's own rows before
    deleting their Performance, CASCADE moves that cleanup to the
    database. `position_type`/`position_id` are replaced by three
    mutually-exclusive nullable foreign keys (`instrument_id`/`voice_id`/
    `choirjob_id`, see PositionColumns) as of the polymorphy-redesign slice
    (2026-09)."""

    __tablename__ = "performance_positions"
    __table_args__ = (
        UniqueConstraint(
            "performance_id",
            "instrument_id",
            "voice_id",
            "choirjob_id",
            name="performance_positions_position_unique",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
            name="performance_positions_position_exactly_one_check",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performances.id", ondelete="CASCADE")
    )
    quantity: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
