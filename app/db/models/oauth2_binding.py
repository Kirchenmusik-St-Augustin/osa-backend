from datetime import datetime

from sqlalchemy import DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Oauth2Binding(Base):
    """Mirrors legacy `oauth2_bindings` exactly (Phase 1 -- no renames, no
    schema changes). `local_id` intentionally has no FK constraint even
    though it references `users.id` in practice -- the real schema dump
    has none, and Phase 1 promises structural fidelity, warts included."""

    __tablename__ = "oauth2_bindings"
    __table_args__ = (UniqueConstraint("provider", "remote_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str]
    remote_id: Mapped[str]
    remote_name: Mapped[str]
    local_id: Mapped[int]
    bound_at: Mapped[datetime] = mapped_column(DateTime())
    lastuse_at: Mapped[datetime] = mapped_column(DateTime())
