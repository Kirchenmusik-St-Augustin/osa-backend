from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Shorturl(Base):
    """Mirrors legacy `shorturls` exactly (Phase 1). A standalone
    redirect-link lookup table, resolved both by the authenticated
    management UI (`/shorturls`, role `shorturls`) and by the public,
    unauthenticated `go.`-subdomain redirect service (see
    app/api/router_includes/go.py) -- no FK from or to any other table."""

    __tablename__ = "shorturls"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(unique=True)
    target: Mapped[str] = mapped_column()
    counter: Mapped[int] = mapped_column(default=0)
    latestcall_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
