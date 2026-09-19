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
from app.db.uuid_pk import uuid_pk


class OrdinariumworkPosition(Base):
    """Pivot row: which Instrument/Voice an Ordinariumwork needs, and in
    what quantity (e.g. "2x Violine, 4x Sopran"). Deliberately restricted
    to instruments/voices ONLY (no choirjobs): `instrument_id`/`voice_id`
    are two mutually-exclusive nullable foreign keys, NOT the shared
    PositionColumns mixin (see app.db.models.position_columns_mixin), which
    also carries a `choirjob_id` column -- this table's exclusion of
    choirjobs is structural (the column doesn't exist at all). No
    standalone routes: managed entirely through Ordinariumwork's own
    create/update ("setup" payload), never directly (see
    ordinariumwork_service.py).

    `created_at`/`updated_at` are TIMESTAMPTZ: `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python. `ordinariumwork_id` is an ON DELETE CASCADE foreign key:
    ordinariumwork_service.delete_ordinariumwork() already deletes this
    table's own rows before deleting their Ordinariumwork, CASCADE moves
    that cleanup to the database."""

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

    id: Mapped[uuid.UUID] = uuid_pk()
    ordinariumwork_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ordinariumworks.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT", onupdate="RESTRICT")
    )
    voice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voices.id", ondelete="RESTRICT", onupdate="RESTRICT")
    )
    quantity: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
