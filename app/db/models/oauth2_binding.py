import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk

# Native Postgres ENUM shared by oauth2_bindings.provider and
# users.auth_lastlogin_provider. Bare string literals instead of a Python
# enum.Enum class, same reasoning as booking_log.booking_type_enum.
oauth2_provider_enum = Enum("google", name="oauth2_provider")


class Oauth2Binding(TimestampColumns, Base):
    """Link between a local user and an external OAuth2 identity. `local_id`
    is an ON DELETE CASCADE foreign key into `users.id` -- an OAuth2
    binding has no meaning independent of the local user it authenticates.

    `bound_at`/`lastuse_at` are TIMESTAMPTZ and Python-managed via
    datetime.now(UTC)."""

    __tablename__ = "oauth2_bindings"
    __table_args__ = (
        UniqueConstraint("provider", "remote_id"),
        Index("oauth2_bindings_local_id_index", "local_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(oauth2_provider_enum)
    remote_id: Mapped[str]
    remote_name: Mapped[str]
    local_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lastuse_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
