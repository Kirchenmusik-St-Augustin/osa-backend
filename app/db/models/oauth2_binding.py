import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class Oauth2Binding(Base):
    """Link between a local user and an external OAuth2 identity. `local_id`
    is an ON DELETE CASCADE foreign key into `users.id` -- an OAuth2
    binding has no meaning independent of the local user it authenticates.

    `bound_at`/`lastuse_at` are TIMESTAMPTZ and Python-managed via
    datetime.now(UTC) (this table has no created_at/updated_at pair, so no
    server_default/trigger applies here)."""

    __tablename__ = "oauth2_bindings"
    __table_args__ = (UniqueConstraint("provider", "remote_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str]
    remote_id: Mapped[str]
    remote_name: Mapped[str]
    local_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lastuse_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
