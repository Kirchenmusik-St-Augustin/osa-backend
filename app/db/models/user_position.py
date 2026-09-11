import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_columns_mixin import PositionColumns
from app.db.uuid_pk import uuid_pk


class UserPosition(PositionColumns, Base):
    """Mirrors legacy `user_positions` exactly (Phase 1). Which
    Instrument/Voice/Choirjob a User is personally qualified to play/take
    on -- the read side that Schritt 6's Cast/`bookable`-candidate
    computation needs (Schritt 6 plan A.1/A.2). The admin UI to assign
    these (User edit form's instrument/voice/choirjob picker) is
    deliberately Schritt 7 (User-/System-Verwaltung), not built here --
    User-Entscheidung during Schritt 6 planning.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `user_id` is an ON DELETE CASCADE foreign key as of the
    FK-hardening slice (2026-09): a qualification row has no meaning
    independent of the user it describes, and no existing check blocks
    deleting a user for having one. `position_type`/`position_id` are
    replaced by three mutually-exclusive nullable foreign keys
    (`instrument_id`/`voice_id`/`choirjob_id`, see PositionColumns) as of
    the polymorphy-redesign slice (2026-09)."""

    __tablename__ = "user_positions"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "instrument_id",
            "voice_id",
            "choirjob_id",
            name="user_positions_position_unique",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
            name="user_positions_position_exactly_one_check",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
