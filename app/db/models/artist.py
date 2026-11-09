import uuid

from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class Artist(TimestampColumns, Base):
    """A composer and/or conductor. `surname`/`givenname` are required;
    the years are four-digit and a death cannot precede the birth (both
    enforced by `artists_years_check`). `composer`/`conductor` are
    orthogonal boolean flags, not mutually exclusive (an Artist row can be
    both, one, or neither)."""

    __tablename__ = "artists"
    __table_args__ = (
        UniqueConstraint("surname", "givenname"),
        CheckConstraint(
            "(birthyear IS NULL OR birthyear BETWEEN 1000 AND 9999) "
            "AND (deathyear IS NULL OR deathyear BETWEEN 1000 AND 9999) "
            "AND (birthyear IS NULL OR deathyear IS NULL OR deathyear >= birthyear)",
            name="artists_years_check",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    surname: Mapped[str]
    givenname: Mapped[str]
    birthyear: Mapped[int | None]
    deathyear: Mapped[int | None]
    description: Mapped[str | None]
    composer: Mapped[bool] = mapped_column(default=False, server_default=false())
    conductor: Mapped[bool] = mapped_column(default=False, server_default=false())
