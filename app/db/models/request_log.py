import uuid
from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.json_types import JsonObject, JsonValue
from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class RequestLog(Base):
    """Mirrors legacy `request_logs` exactly (structural 1:1 transfer, no
    new FK constraints beyond what Legacy had). Written by
    `app.api.middleware.request_logging.RequestLoggingMiddleware` for every
    non-excluded request -- 1:1 legacy's `RequestLog::process()`, called
    from `RequestLogging` middleware's `terminate()` hook. `client_ips`/
    `request_input`/`response_content` are native JSONB columns (were
    varchar holding manually json.dumps()-encoded text before this slice)
    -- SQLAlchemy handles (de)serialization automatically, the service
    layer works with plain Python objects (list/dict/etc.) end to end.
    `client_user_agent_id`/`user_id` are nullable, ON DELETE SET NULL
    foreign keys as of the FK-hardening slice (2026-09): an anonymous or
    since-deleted client/user never blocks or removes this table's own
    audit trail entries. `created_at`/`updated_at` are TIMESTAMPTZ as of
    the TIMESTAMPTZ + audit-trigger hardening slice (2026-09): `created_at`
    is populated by the database's own DEFAULT now(), `updated_at` by the
    shared set_updated_at() BEFORE UPDATE trigger -- neither is assigned
    from Python anymore."""

    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    client_ip: Mapped[str]
    client_ips: Mapped[list[str] | None] = mapped_column(JSONB())
    client_user_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("client_user_agents.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    request_method: Mapped[str]
    request_path: Mapped[str]
    request_input: Mapped[JsonObject | None] = mapped_column(JSONB())
    response_status: Mapped[int]
    response_content: Mapped[JsonValue | None] = mapped_column(JSONB())
    memory_usage: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
