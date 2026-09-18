import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, Index, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class PersonalAccessToken(Base):
    """Backs the JWT refresh flow, one row per issued refresh token. The
    table's generic columns are repurposed: `token` holds the JWT-ID
    (jti), `abilities` (nullable TEXT) holds the refresh token hash,
    `expires_at` holds the refresh token's expiry. `refresh_token_hash` is
    a hybrid property so callers keep reading/writing a meaningful name
    while the underlying `abilities` column keeps its generic name.

    `user_id` is a real column with an ON DELETE CASCADE foreign key to
    `users.id` -- the JWT refresh flow only ever issues tokens to Users, so
    no polymorphic owner type is needed.

    `id`/`user_id` are UUIDv7 (server-generated via Postgres's native
    `uuidv7()`, see app.db.uuid_pk) as of the UUID-migration slice
    (2026-09), replacing the former integer autoincrement sequence.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `last_used_at`/`expires_at` are also TIMESTAMPTZ now
    (same slice) but stay Python-managed -- only their storage type
    changed."""

    __tablename__ = "personal_access_tokens"
    __table_args__ = (
        Index("personal_access_tokens_user_id_index", "user_id"),
        Index("personal_access_tokens_token_unique", "token", unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    name: Mapped[str]  # e.g. "session"
    token: Mapped[str]  # JWT-ID (jti)
    abilities: Mapped[str | None]  # repurposed: refresh token hash
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # refresh token expiry
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )

    @hybrid_property
    def refresh_token_hash(self) -> str | None:
        return self.abilities

    @refresh_token_hash.inplace.setter
    def _refresh_token_hash_setter(self, value: str | None) -> None:
        self.abilities = value
