from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PerformancePosition(Base):
    """Pivot row: which Instrument/Voice/Choirjob a Performance needs, and
    in what quantity. Unlike OrdinariumworkPosition, Performance's
    position_type polymorphy legitimately includes ALL THREE types --
    confirmed live: Legacy's Performance uses instruments/voices/choirjobs,
    only Ordinariumwork's CHECK constraint excludes choirjobs (see
    project_osa_performance_domain_research memory)."""

    __tablename__ = "performance_positions"
    __table_args__ = (
        UniqueConstraint("performance_id", "position_type", "position_id"),
        CheckConstraint("position_type IN ('instruments', 'voices', 'choirjobs')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    position_type: Mapped[str]
    position_id: Mapped[int]
    quantity: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
