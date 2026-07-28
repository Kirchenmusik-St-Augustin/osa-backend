from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Role(Base):
    """Mirrors legacy `roles` exactly (Phase 1 -- no renames, no schema
    changes). Five rows exist in practice: planner, disponent, billing,
    scores, shorturls (see project_osa_legacy_domain_map memory) --
    `administrator` is a separate boolean flag on `users`, not a role row."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    label: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
