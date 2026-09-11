import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.uuid_pk import uuid_pk


class RepertoireWorkColumns:
    """Shared columns for Legacy's Ordinariumwork/Propriumwork models --
    both are 100% identical in the Legacy schema (name/description/
    demanding/artist_id/duration/timestamps). Ordinariumwork additionally
    has a Positions sub-resource (ordinariumwork_positions, see
    ordinariumwork_position.py) that Propriumwork doesn't have.
    `artist_id` is an ON DELETE RESTRICT foreign key as of the FK-hardening
    slice (2026-09): artist_service._artist_has_dependencies() already
    blocks deleting an Artist referenced from either Ordinariumwork or
    Propriumwork, RESTRICT enforces that same rule at the database level
    for both tables sharing this mixin.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09) -- same server_default/
    trigger split as CoreelementColumns above.

    `id`/`artist_id` are UUIDv7 (server-generated via Postgres's native
    `uuidv7()`, see app.db.uuid_pk) as of the UUID-migration slice
    (2026-09), replacing the former integer autoincrement sequence."""

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str]
    description: Mapped[str | None]
    demanding: Mapped[bool] = mapped_column(default=False)
    artist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artists.id", ondelete="RESTRICT")
    )
    duration: Mapped[int | None]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
