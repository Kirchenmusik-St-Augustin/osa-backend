import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class PersonalAccessToken(TimestampColumns, Base):
    """Backs the JWT refresh flow, one row per session: `jti` is the JWT ID
    that identifies the session, `refresh_token_hash` the hash of the current
    refresh secret. The absolute lifetime of a session is computed from
    `created_at`, its idle time from `last_used_at`.

    `user_id` is a real column with an ON DELETE CASCADE foreign key to
    `users.id` -- the JWT refresh flow only ever issues tokens to Users, so
    no polymorphic owner type is needed.

    `id`/`user_id` are UUIDv7 (server-generated via Postgres's native
    `uuidv7()`, see app.db.uuid_pk).

    `last_used_at` is TIMESTAMPTZ and stays Python-managed."""

    __tablename__ = "personal_access_tokens"
    __table_args__ = (
        Index("personal_access_tokens_user_id_index", "user_id"),
        Index("personal_access_tokens_jti_unique", "jti", unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    jti: Mapped[str]
    refresh_token_hash: Mapped[str | None]
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
