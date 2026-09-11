import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class PerformanceProprium(Base):
    """Pivot row: which Propriumwork fills which liturgical Propriumelement
    slot (e.g. "Graduale") for a Performance. Unique per (performance,
    element) -- only one work per liturgical slot per performance.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. Foreign keys are deliberately asymmetric as of the
    FK-hardening slice (2026-09): `performance_id` is ON DELETE CASCADE
    (performance_service.delete_performance() already deletes this table's
    own rows before deleting their Performance), `propriumelement_id`/
    `propriumwork_id` are ON DELETE RESTRICT (coreelement_service.
    _propriumelement_has_dependent_performances()/propriumwork_service.
    _propriumwork_has_dependencies() already block deleting either while
    referenced here)."""

    __tablename__ = "performance_proprium"
    __table_args__ = (UniqueConstraint("performance_id", "propriumelement_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performances.id", ondelete="CASCADE")
    )
    propriumelement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("propriumelements.id", ondelete="RESTRICT")
    )
    propriumwork_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("propriumworks.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
