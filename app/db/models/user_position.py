import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.position_columns_mixin import PositionColumns
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class UserPosition(TimestampColumns, PositionColumns, Base):
    """Which Instrument/Voice/Choirjob a User is personally qualified to
    play/take on -- the read side of the Cast/`bookable`-candidate
    computation, assigned through the User edit form's
    instrument/voice/choirjob picker (see user_position_service.py).

    `user_id` is an ON DELETE CASCADE foreign key: a qualification
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
        Index("user_positions_instrument_id_index", "instrument_id"),
        Index("user_positions_voice_id_index", "voice_id"),
        Index("user_positions_choirjob_id_index", "choirjob_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
