import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class PerformanceRehearsal(TimestampColumns, Base):
    """A single rehearsal slot (date/time + free-text location, NOT an FK to the
    Location model) for a Performance. Always fully replaced (delete-all, recreate) on
    every Performance save, never diffed -- see performance_service.py.

    `schedule` deliberately stays a naive TIMESTAMP: it's
    user-entered local wall-clock time in Settings.app_timezone, not a UTC
    instant (see app.core.datetime_utils module docstring). `performance_id`
    is an ON DELETE CASCADE foreign key:
    performance_service.delete_performance() already deletes this table's
    own rows before deleting their Performance, CASCADE moves that cleanup
    to the database."""

    __tablename__ = "performance_rehearsals"
    __table_args__ = (UniqueConstraint("performance_id", "schedule"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    performance_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("performances.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    schedule: Mapped[datetime] = mapped_column(DateTime())
    comment: Mapped[str | None]
