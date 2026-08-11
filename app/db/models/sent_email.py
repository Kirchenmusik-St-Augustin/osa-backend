from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SentEmail(Base):
    """Mirrors legacy `sent_emails` exactly (Phase 1). `mail_from` maps to
    the actual `from` column (a reserved Python keyword) via
    mapped_column's explicit column-name argument. `headers` is
    repurposed as a free-text "template key" marker (e.g.
    "password-reset") by the mailer, not real MIME headers -- matches
    legacy's actual usage of the column, not a schema change."""

    __tablename__ = "sent_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    mail_from: Mapped[str | None] = mapped_column("from")
    to: Mapped[str | None]
    cc: Mapped[str | None]
    bcc: Mapped[str | None]
    subject: Mapped[str | None]
    body: Mapped[str | None]
    headers: Mapped[str | None]
    attachments: Mapped[str | None]
    mailer: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
