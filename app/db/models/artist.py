import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class Artist(Base):
    """Mirrors legacy `artists` exactly (structural 1:1 transfer -- no
    renames, no schema changes). `surname`/`givenname` are nullable in the
    real legacy schema even though app-level validation always requires
    them -- structural
    parity keeps the model nullable regardless (see coreelement's
    Location.address for the same pattern). `composer`/`conductor` are
    orthogonal boolean flags, not mutually exclusive (an Artist row can be
    both, one, or neither).

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "artists"
    __table_args__ = (UniqueConstraint("surname", "givenname"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    surname: Mapped[str | None]
    givenname: Mapped[str | None]
    birthyear: Mapped[int | None]
    deathyear: Mapped[int | None]
    description: Mapped[str | None]
    composer: Mapped[bool] = mapped_column(default=False)
    conductor: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
