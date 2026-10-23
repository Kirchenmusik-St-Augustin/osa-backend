import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class UserRole(TimestampColumns, Base):
    """Pure pivot table (user <-> role) that nevertheless carries the
    standard created_at and updated_at columns like every other table, not
    as a mapping-table exemption.

    Both foreign keys have an explicit `ondelete=`, deliberately asymmetric: `user_id`
    is ON DELETE CASCADE (a role grant is meaningless without its user, and no existing
    check blocks deleting a user for having roles), `role_id` is ON DELETE RESTRICT
    (coreelement_service._role_has_dependent_users() already blocks deleting a Role that
    is still assigned to a user -- CASCADE here would silently strip that user's role
    grant instead, which is security-relevant and must fail loudly)."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id"),
        Index("user_roles_role_id_index", "role_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT", onupdate="RESTRICT")
    )
