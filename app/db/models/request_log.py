from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.json_types import JsonObject, JsonValue
from app.db.database import Base


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
    No FK constraints (Phase 1, `client_user_agent_id`/`user_id` are plain
    ints). `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ
    + audit-trigger hardening slice (2026-09): `created_at` is populated
    by the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore."""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_ip: Mapped[str]
    client_ips: Mapped[list[str] | None] = mapped_column(JSONB())
    client_user_agent_id: Mapped[int | None]
    user_id: Mapped[int | None]
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
