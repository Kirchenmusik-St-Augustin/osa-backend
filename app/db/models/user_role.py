import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class UserRole(Base):
    """Mirrors legacy `user_roles` (pure pivot table) exactly, including
    its `created_at`/`updated_at` columns -- Phase 1's structural-parity
    transfer gave every legacy table these two columns regardless of
    whether it was a junction table, and this one is no exception
    (confirmed present in the real legacy schema). The TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09) therefore treats this table
    the same as every other created_at/updated_at pair in the schema, not
    as a mapping-table exemption: the columns already exist and hold
    genuinely-UTC data, so excluding them here would mean dropping live
    columns, which is out of scope for a timestamp-hardening slice.
    `created_at` is populated by the database's own DEFAULT now(),
    `updated_at` by the shared set_updated_at() BEFORE UPDATE trigger --
    neither is assigned from Python anymore.

    Both foreign keys got an explicit `ondelete=` as of the FK-hardening
    slice (2026-09), deliberately asymmetric: `user_id` is ON DELETE
    CASCADE (a role grant is meaningless without its user, and no existing
    check blocks deleting a user for having roles), `role_id` is ON DELETE
    RESTRICT (coreelement_service._role_has_dependent_users() already
    blocks deleting a Role that is still assigned to a user -- CASCADE here
    would silently strip that user's role grant instead, which is
    security-relevant and must fail loudly)."""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
