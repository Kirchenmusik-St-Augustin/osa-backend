from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

if TYPE_CHECKING:
    from app.db.models.user import User


class Role(Base):
    """Mirrors legacy `roles` exactly (Phase 1 -- no renames, no schema
    changes). Five rows exist in practice: planner, disponent, billing,
    scores, shorturls -- `administrator` is a separate boolean flag on
    `users`, not a role row."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())

    # Back-reference to User.roles -- added for Schritt 7's "Meine
    # Ansprechpersonen" (support_service.list_roles_with_contacts()), which
    # needs one N+1-safe selectinload(Role.users) query for all roles+their
    # assigned users at once.
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="user_roles",
        primaryjoin="Role.id == UserRole.role_id",
        secondaryjoin="User.id == UserRole.user_id",
        viewonly=True,
    )
