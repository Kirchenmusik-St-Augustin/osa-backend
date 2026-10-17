import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class PasswordResetToken(Base):
    """Password-reset token row: at most one active reset token per email
    (unique constraint); a new request replaces the previous row in a single
    upsert (see auth_service.request_password_reset). `token` holds the hash
    of the emailed token, never the token itself.

    `created_at` is TIMESTAMPTZ, populated by the database's own DEFAULT
    now() and moved forward by every replacing request, it is the base of the
    token's lifetime; `updated_at` is maintained by the set_updated_at()
    trigger."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (UniqueConstraint("email"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str]
    token: Mapped[str]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
