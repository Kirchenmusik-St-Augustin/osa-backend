from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Artist(Base):
    """Mirrors legacy `artists` exactly (structural 1:1 transfer -- no
    renames, no schema changes). `surname`/`givenname` are nullable in the
    real legacy schema even though app-level validation always requires
    them -- structural
    parity keeps the model nullable regardless (see coreelement's
    Location.address for the same pattern). `composer`/`conductor` are
    orthogonal boolean flags, not mutually exclusive (an Artist row can be
    both, one, or neither)."""

    __tablename__ = "artists"
    __table_args__ = (UniqueConstraint("surname", "givenname"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    surname: Mapped[str | None]
    givenname: Mapped[str | None]
    birthyear: Mapped[int | None]
    deathyear: Mapped[int | None]
    description: Mapped[str | None]
    composer: Mapped[bool] = mapped_column(default=False)
    conductor: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
