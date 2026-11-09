import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.oauth2_binding import oauth2_provider_enum
from app.db.models.role import Role
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class User(TimestampColumns, Base):
    """Application user. Column names stay as-is (auth_password,
    auth_locked, etc.) in Python as well.

    `email_verified_at`/`auth_lastlogin`/`auth_lastsignal`/
    `auth_lastlogout`/`deleted_at` are TIMESTAMPTZ and stay Python-managed
    via datetime.now(UTC) -- no server_default/trigger, per the rule that
    keeps every business-event timestamp Python-managed."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("surname", "givenname"),
        CheckConstraint(
            "email IS NULL OR email = lower(email)", name="users_email_lowercase_check"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    surname: Mapped[str]
    givenname: Mapped[str]
    email: Mapped[str | None] = mapped_column(unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone: Mapped[str | None]
    auth_password: Mapped[str | None]
    auth_remember_token: Mapped[str | None]
    auth_lastlogin_provider: Mapped[str | None] = mapped_column(oauth2_provider_enum)
    auth_lastlogin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_lastsignal: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_lastlogout: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_locked: Mapped[bool] = mapped_column(default=False, server_default=false())
    administrator: Mapped[bool] = mapped_column(default=False, server_default=false())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles",
        primaryjoin="User.id == UserRole.user_id",
        secondaryjoin="Role.id == UserRole.role_id",
        viewonly=True,
    )
