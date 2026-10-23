import uuid

from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class PasswordResetToken(TimestampColumns, Base):
    """Password-reset token row: at most one active reset token per email
    (unique constraint); a new request replaces the previous row in a single
    upsert (see auth_service.request_password_reset). `token` holds the hash
    of the emailed token, never the token itself.

    `created_at` is moved forward by every replacing request and is the base
    of the token's lifetime."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (UniqueConstraint("email"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str]
    token: Mapped[str]
