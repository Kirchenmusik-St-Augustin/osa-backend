import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class ClientUserAgent(Base):
    """A dedup table for raw User-Agent header strings, referenced by
    `request_logs.client_user_agent_id`. `string` is UNIQUE:
    request_log_service's get-or-create against this table runs on every
    HTTP request, and the constraint is what makes the IntegrityError-based
    race handling there actually correct rather than just optimistic.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the FK-hardening
    follow-up slice (2026-09): `created_at` is populated by the database's
    own DEFAULT now(), `updated_at` by the shared set_updated_at() BEFORE
    UPDATE trigger, same as every other non-Legacy-mirrored table -- this
    table has no update path in practice (rows are only ever inserted, via
    get-or-create), so `updated_at` stays NULL for the lifetime of a row."""

    __tablename__ = "client_user_agents"

    id: Mapped[uuid.UUID] = uuid_pk()
    string: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
