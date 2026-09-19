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
    """Which Instrument/Voice/Choirjob a User is personally qualified to
    play/take on -- the read side of the Cast/`bookable`-candidate
    computation, assigned through the User edit form's
    instrument/voice/choirjob picker (see user_position_service.py).

    `created_at`/`updated_at` are TIMESTAMPTZ: `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python. `user_id` is an ON DELETE CASCADE foreign key: a qualification
    row has no meaning independent of the user it describes, and no
    existing check blocks deleting a user for having one. The position is
    one of three mutually-exclusive nullable foreign keys
    (`instrument_id`/`voice_id`/`choirjob_id`, see PositionColumns)."""

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
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
