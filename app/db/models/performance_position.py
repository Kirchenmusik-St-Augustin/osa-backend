import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_columns_mixin import PositionColumns
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class PerformancePosition(TimestampColumns, PositionColumns, Base):
    """Pivot row: which Instrument/Voice/Choirjob a Performance needs, and
    in what quantity. Unlike OrdinariumworkPosition, Performance's position
    polymorphy legitimately includes ALL THREE types
    (instruments/voices/choirjobs) -- only Ordinariumwork excludes
    choirjobs.

    `performance_id` is an ON DELETE CASCADE foreign key:
    performance_service.delete_performance() already deletes this table's
    own rows before deleting their Performance, CASCADE moves that cleanup
    to the database. A position's owner is one of three mutually-exclusive
    nullable foreign keys (`instrument_id`/`voice_id`/`choirjob_id`, see
    PositionColumns)."""

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
        CheckConstraint(
            "quantity BETWEEN 1 AND 99",
            name="performance_positions_quantity_check",
        ),
        Index("performance_positions_instrument_id_index", "instrument_id"),
        Index("performance_positions_voice_id_index", "voice_id"),
        Index("performance_positions_choirjob_id_index", "choirjob_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performances.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    quantity: Mapped[int]
