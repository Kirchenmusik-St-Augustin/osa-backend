from datetime import datetime

from sqlalchemy import DateTime, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PasswordResetToken(Base):
    """Password-reset token row: the table has no id/PK column, just
    `email` (non-unique index), `token`, `created_at`. `email` is declared
    as the SQLAlchemy-level primary key purely so the ORM's identity
    map/delete() work -- an ORM-only declaration, not a DB-level
    constraint. At most one active reset token per email in practice: a new
    request deletes the previous row first (see
    auth_service.request_password_reset).

    `created_at` is TIMESTAMPTZ, populated by the database's own DEFAULT
    now() -- there is no `updated_at` column here, so there is no
    set_updated_at() trigger on this table either."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("password_resets_email_index", "email"),)

    email: Mapped[str] = mapped_column(primary_key=True)
    token: Mapped[str]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
