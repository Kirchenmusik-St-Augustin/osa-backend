import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, FetchedValue, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.json_types import JsonObject, JsonValue
from app.db.database import Base
from app.db.uuid_pk import uuid_pk

# The nine methods of RFC 9110. A request with any other method is answered
# with 405 and not logged (see request_log_service.record_request).
HTTP_METHODS = (
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "DELETE",
    "CONNECT",
    "OPTIONS",
    "TRACE",
    "PATCH",
)
http_method_enum = Enum(*HTTP_METHODS, name="http_method")


class RequestLog(Base):
    """Audit-trail entry for every non-excluded request, written by
    `app.api.middleware.request_logging.RequestLoggingMiddleware`.
    `client_ips`/`request_input`/`response_content` are native JSONB
    columns -- SQLAlchemy handles (de)serialization automatically, the
    service layer works with plain Python objects (list/dict/etc.) end to
    end. `client_user_agent_id`/`user_id` are nullable, ON DELETE SET NULL
    foreign keys: an anonymous or since-deleted client/user never blocks or
    removes this table's own audit trail entries. `created_at`/
    `updated_at` are TIMESTAMPTZ: `created_at` is populated by the
    database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python."""

    __tablename__ = "request_logs"
    __table_args__ = (
        Index("request_logs_client_user_agent_id_index", "client_user_agent_id"),
        Index("request_logs_user_id_index", "user_id"),
        Index("request_logs_created_at_index", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    client_ip: Mapped[str]
    client_ips: Mapped[list[str] | None] = mapped_column(JSONB())
    client_user_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("client_user_agents.id", ondelete="SET NULL", onupdate="SET NULL")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", onupdate="SET NULL")
    )
    request_method: Mapped[str] = mapped_column(http_method_enum)
    request_path: Mapped[str]
    request_input: Mapped[JsonObject | None] = mapped_column(JSONB())
    response_status: Mapped[int]
    response_content: Mapped[JsonValue | None] = mapped_column(JSONB())
    memory_usage: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
