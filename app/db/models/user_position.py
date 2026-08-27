from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserPosition(Base):
    """Mirrors legacy `user_positions` exactly (Phase 1). Which
    Instrument/Voice/Choirjob a User is personally qualified to play/take
    on -- the read side that Schritt 6's Cast/`bookable`-candidate
    computation needs (Schritt 6 plan A.1/A.2). The admin UI to assign
    these (User edit form's instrument/voice/choirjob picker) is
    deliberately Schritt 7
    (User-/System-Verwaltung), not built here -- User-Entscheidung during
    Schritt 6 planning."""

    __tablename__ = "user_positions"
    __table_args__ = (
        UniqueConstraint("user_id", "position_type", "position_id"),
        CheckConstraint("position_type IN ('instruments', 'voices', 'choirjobs')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int]
    position_type: Mapped[str]
    position_id: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
