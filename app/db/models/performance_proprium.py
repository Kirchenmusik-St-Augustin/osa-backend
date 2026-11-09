import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class PerformanceProprium(TimestampColumns, Base):
    """Pivot row: which Propriumwork fills which liturgical Propriumelement
    slot (e.g. "Graduale") for a Performance. Unique per (performance,
    element) -- only one work per liturgical slot per performance.

    Foreign keys are deliberately asymmetric: `performance_id` is ON
    DELETE CASCADE (performance_service.delete_performance() already deletes
    this table's own rows before deleting their Performance),
    `propriumelement_id`/`propriumwork_id` are ON DELETE RESTRICT
    (coreelement_service.
    _propriumelement_has_dependent_performances()/propriumwork_service.
    _propriumwork_has_dependencies() already block deleting either while
    referenced here)."""

    __tablename__ = "performance_proprium"
    __table_args__ = (
        UniqueConstraint("performance_id", "propriumelement_id"),
        Index("performance_proprium_propriumelement_id_index", "propriumelement_id"),
        Index("performance_proprium_propriumwork_id_index", "propriumwork_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performances.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    propriumelement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("propriumelements.id", ondelete="RESTRICT", onupdate="RESTRICT")
    )
    propriumwork_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("propriumworks.id", ondelete="RESTRICT", onupdate="RESTRICT")
    )
