import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    FetchedValue,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class Artist(Base):
    """A composer and/or conductor. `surname`/`givenname` are required;
    the years are four-digit and a death cannot precede the birth (both
    enforced by `artists_years_check`). `composer`/`conductor` are
    orthogonal boolean flags, not mutually exclusive (an Artist row can be
    both, one, or neither).

    `created_at`/`updated_at` are TIMESTAMPTZ: `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python."""

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
