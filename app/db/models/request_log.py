from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class RequestLog(Base):
    """Mirrors legacy `request_logs` exactly (Phase 1, see
    tests/fixtures/legacy_schema.sql for the exact column set). Written by
    `app.api.middleware.request_logging.RequestLoggingMiddleware` for every
    non-excluded request -- 1:1 legacy's `RequestLog::process()`, called
    from `RequestLogging` middleware's `terminate()` hook. `client_ips`/
    `request_input`/`response_content` hold JSON-encoded text (legacy:
    Eloquent `cast('array')` over a `text` column) -- (de)serialization is
    the service layer's job, not the model's, this class only mirrors the
    raw DB shape. No FK constraints (Phase 1, `client_user_agent_id`/
    `user_id` are plain ints)."""

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_ip: Mapped[str]
    client_ips: Mapped[str | None]
    client_user_agent_id: Mapped[int | None]
    user_id: Mapped[int | None]
    request_method: Mapped[str]
    request_path: Mapped[str]
    request_input: Mapped[str | None]
    response_status: Mapped[int]
    response_content: Mapped[str | None]
    memory_usage: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
