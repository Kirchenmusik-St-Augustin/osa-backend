import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class UserRole(Base):
    """Pure pivot table (user <-> role) that nevertheless carries
    `created_at`/`updated_at` columns and treats them like every other
    created_at/updated_at pair in the schema, not as a mapping-table
    exemption: the columns hold genuinely-UTC data. `created_at` is
    populated by the database's own DEFAULT now(), `updated_at` by the
    shared set_updated_at() BEFORE UPDATE trigger -- neither is assigned
    from Python.

    Both foreign keys have an explicit `ondelete=`, deliberately asymmetric: `user_id`
    is ON DELETE CASCADE (a role grant is meaningless without its user, and no existing
    check blocks deleting a user for having roles), `role_id` is ON DELETE RESTRICT
    (coreelement_service._role_has_dependent_users() already blocks deleting a Role that
    is still assigned to a user -- CASCADE here would silently strip that user's role
    grant instead, which is security-relevant and must fail loudly)."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT", onupdate="RESTRICT")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
