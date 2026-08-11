from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PerformanceRehearsal(Base):
    """A single rehearsal slot (date/time + free-text location, NOT an FK
    to the Location model -- Legacy stores this as a plain string) for a
    Performance. Always fully replaced (delete-all, recreate) on every
    Performance save, never diffed -- see performance_service.py."""

    __tablename__ = "performance_rehearsals"
    __table_args__ = (UniqueConstraint("performance_id", "schedule"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    schedule: Mapped[datetime] = mapped_column(DateTime())
    comment: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
