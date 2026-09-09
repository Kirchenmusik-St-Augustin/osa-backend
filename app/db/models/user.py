from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.role import Role


class User(Base):
    """Mirrors legacy `users` exactly (Phase 1 -- no renames, no schema
    changes). Column names stay as-is (auth_password, auth_locked, etc.)
    even in Python, per the Phase-1 "structure identical" rule.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger. `email_verified_at`/
    `auth_lastlogin`/`auth_lastsignal`/`auth_lastlogout`/`deleted_at` are
    also TIMESTAMPTZ now (same slice) but stay Python-managed via
    datetime.now(UTC) -- only their storage type changed, no
    server_default/trigger, per the same rule that keeps every other
    non-created_at/updated_at business-event timestamp Python-managed."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("surname", "givenname"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    surname: Mapped[str]
    givenname: Mapped[str]
    email: Mapped[str | None] = mapped_column(unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    phone: Mapped[str | None]
    auth_password: Mapped[str | None]
    auth_remember_token: Mapped[str | None]
    auth_lastlogin_provider: Mapped[str | None]
    auth_lastlogin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_lastsignal: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_lastlogout: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_locked: Mapped[bool] = mapped_column(default=False)
    administrator: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles",
        primaryjoin="User.id == UserRole.user_id",
        secondaryjoin="Role.id == UserRole.role_id",
        viewonly=True,
    )
