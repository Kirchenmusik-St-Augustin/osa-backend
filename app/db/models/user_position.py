from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_type_enum import position_type_enum


class UserPosition(Base):
    """Mirrors legacy `user_positions` exactly (Phase 1). Which
    Instrument/Voice/Choirjob a User is personally qualified to play/take
    on -- the read side that Schritt 6's Cast/`bookable`-candidate
    computation needs (Schritt 6 plan A.1/A.2). The admin UI to assign
    these (User edit form's instrument/voice/choirjob picker) is
    deliberately Schritt 7
    (User-/System-Verwaltung), not built here -- User-Entscheidung during
    Schritt 6 planning. `position_type` is the shared native Postgres
    ENUM (see app.db.models.position_type_enum) as of the enum-hardening
    slice (2026-09), replacing its former CHECK constraint.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `user_id` is an ON DELETE CASCADE foreign key as of the
    FK-hardening slice (2026-09): a qualification row has no meaning
    independent of the user it describes, and no existing check blocks
    deleting a user for having one."""

    __tablename__ = "user_positions"
    __table_args__ = (UniqueConstraint("user_id", "position_type", "position_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    position_type: Mapped[str] = mapped_column(position_type_enum)
    position_id: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
