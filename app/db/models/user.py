from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.role import Role


class User(Base):
    """Mirrors legacy `users` exactly (Phase 1 -- no renames, no schema
    changes). Column names stay as-is (auth_password, auth_locked, etc.)
    even in Python, per the Phase-1 "structure identical" rule."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("surname", "givenname"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    surname: Mapped[str]
    givenname: Mapped[str]
    email: Mapped[str | None] = mapped_column(unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime())
    phone: Mapped[str | None]
    auth_password: Mapped[str | None]
    auth_remember_token: Mapped[str | None]
    auth_lastlogin_provider: Mapped[str | None]
    auth_lastlogin: Mapped[datetime | None] = mapped_column(DateTime())
    auth_lastsignal: Mapped[datetime | None] = mapped_column(DateTime())
    auth_lastlogout: Mapped[datetime | None] = mapped_column(DateTime())
    auth_locked: Mapped[bool] = mapped_column(default=False)
    administrator: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime())

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles",
        primaryjoin="User.id == UserRole.user_id",
        secondaryjoin="Role.id == UserRole.role_id",
        viewonly=True,
    )
