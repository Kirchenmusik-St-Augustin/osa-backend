import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class PerformanceRehearsal(Base):
    """A single rehearsal slot (date/time + free-text location, NOT an FK
    to the Location model -- Legacy stores this as a plain string) for a
    Performance. Always fully replaced (delete-all, recreate) on every
    Performance save, never diffed -- see performance_service.py.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `schedule` deliberately stays a naive TIMESTAMP: it's
    user-entered local wall-clock time in Settings.app_timezone, not a
    UTC instant (see app.core.datetime_utils module docstring).
    `performance_id` is an ON DELETE CASCADE foreign key as of the
    FK-hardening slice (2026-09): performance_service.delete_performance()
    already deletes this table's own rows before deleting their
    Performance, CASCADE moves that cleanup to the database."""

    __tablename__ = "performance_rehearsals"
    __table_args__ = (UniqueConstraint("performance_id", "schedule"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performances.id", ondelete="CASCADE")
    )
    schedule: Mapped[datetime] = mapped_column(DateTime())
    comment: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
