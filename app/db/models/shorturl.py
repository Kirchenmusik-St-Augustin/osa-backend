import uuid
from datetime import datetime

from sqlalchemy import DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class Shorturl(TimestampColumns, Base):
    """A standalone redirect-link lookup table, resolved both by the authenticated
    management UI (`/shorturls`, role `shorturls`) and by the public,
    unauthenticated `go.`-subdomain redirect service (see
    app/api/router_includes/go.py) -- no FK from or to any other table.

    `latestcall_at` is TIMESTAMPTZ and stays Python-managed."""

    __tablename__ = "shorturls"

    id: Mapped[uuid.UUID] = uuid_pk()
    path: Mapped[str] = mapped_column(unique=True)
    target: Mapped[str] = mapped_column()
    counter: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    latestcall_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
