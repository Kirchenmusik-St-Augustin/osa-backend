from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Shorturl(Base):
    """Mirrors legacy `shorturls` exactly (Phase 1). A standalone
    redirect-link lookup table, resolved both by the authenticated
    management UI (`/shorturls`, role `shorturls`) and by the public,
    unauthenticated `go.`-subdomain redirect service (see
    app/api/router_includes/go.py) -- no FK from or to any other table.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `latestcall_at` is also TIMESTAMPTZ now (same slice)
    but stays Python-managed -- only its storage type changed."""

    __tablename__ = "shorturls"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(unique=True)
    target: Mapped[str] = mapped_column()
    counter: Mapped[int] = mapped_column(default=0)
    latestcall_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
