from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class RepertoireWorkColumns:
    """Shared columns for Legacy's Ordinariumwork/Propriumwork models --
    both are 100% identical in the Legacy schema (name/description/
    demanding/artist_id/duration/timestamps). Ordinariumwork additionally
    has a Positions sub-resource (ordinariumwork_positions, see
    ordinariumwork_position.py) that Propriumwork doesn't have.
    `artist_id` is a plain int, not a ForeignKey: the real legacy schema
    has zero FK constraints anywhere (Legacy enforces referential
    integrity purely at the application level), so the structural 1:1
    transfer keeps that exactly, per CLAUDE.md's structural-parity
    mandate."""

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    description: Mapped[str | None]
    demanding: Mapped[bool] = mapped_column(default=False)
    artist_id: Mapped[int]
    duration: Mapped[int | None]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
