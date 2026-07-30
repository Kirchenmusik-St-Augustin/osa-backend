from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BookingLog(Base):
    """Mirrors legacy `booking_logs` exactly (Phase 1). One append-only row
    per book/unbook transition -- deliberately NO unique index, duplicates
    are the expected shape (every promote/demote/cast-change produces a new
    row). `notified_at` is set by the scheduled
    `notify_upcoming_booking_status` job once a user has been emailed about
    this transition (see booking_jobs.py, a port of Legacy's
    `BookingLog::checkNotificationForUpcomingPerformances()`). Never cleaned
    up on Performance deletion -- Legacy has no FK/cleanup path either,
    historical log rows are meant to outlive the Performance they
    describe (see project_osa_performance_domain_research memory)."""

    __tablename__ = "booking_logs"
    __table_args__ = (
        CheckConstraint("booking_type IN ('book', 'unbook')"),
        CheckConstraint("position_type IN ('instruments', 'voices', 'choirjobs')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_id: Mapped[int]
    user_id: Mapped[int]
    booking_type: Mapped[str]
    position_type: Mapped[str]
    position_id: Mapped[int]
    fee: Mapped[int]
    notified_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
