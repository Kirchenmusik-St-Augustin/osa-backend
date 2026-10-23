import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk

if TYPE_CHECKING:
    from app.db.models.user import User


class Role(TimestampColumns, Base):
    """Application role. The `order` column is `sort_order` at the DB level
    (Postgres always requires `order` to be double-quoted as an
    identifier); the Python attribute/ORM-facing name stays `order` via
    mapped_column's explicit column-name argument (same alias pattern as
    SentEmail.mail_from, see sent_email.py). Five rows exist in practice:
    planner, disponent, billing, scores, shorturls -- `administrator` is a
    separate boolean flag on `users`, not a role row."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    order: Mapped[int] = mapped_column("sort_order", default=0)

    # Back-reference to User.roles: the "Meine Ansprechpersonen" page loads all
    # roles together with their assigned users in one N+1-safe
    # selectinload(Role.users) query (support_service).
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="user_roles",
        primaryjoin="Role.id == UserRole.role_id",
        secondaryjoin="User.id == UserRole.user_id",
        viewonly=True,
    )
