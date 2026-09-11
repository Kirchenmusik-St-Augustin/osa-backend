import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class SentEmail(Base):
    """Mirrors legacy `sent_emails` exactly (Phase 1). `mail_from` maps to
    the actual `from` column (a reserved Python keyword) via
    mapped_column's explicit column-name argument. `headers` is
    repurposed as a free-text "template key" marker (e.g.
    "password-reset") by the mailer, not real MIME headers -- matches
    legacy's actual usage of the column, not a schema change.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "sent_emails"

    id: Mapped[uuid.UUID] = uuid_pk()
    mail_from: Mapped[str | None] = mapped_column("from")
    to: Mapped[str | None]
    cc: Mapped[str | None]
    bcc: Mapped[str | None]
    subject: Mapped[str | None]
    body: Mapped[str | None]
    headers: Mapped[str | None]
    mailer: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
