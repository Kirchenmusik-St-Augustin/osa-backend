import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, FetchedValue, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.json_types import JsonObject
from app.db.database import Base
from app.db.uuid_pk import uuid_pk

# The first six events are written by the application (see AuthEvent in
# app.services.auth_service); the last four only exist in rows from earlier
# years.
auth_event_enum = Enum(
    "Login",
    "Failed",
    "Lockout",
    "Logout",
    "Verified",
    "PasswordReset",
    "Attempting",
    "Validated",
    "OtherDeviceLogout",
    "CurrentDeviceLogout",
    name="auth_event",
)


class AuthLog(Base):
    """Write-only audit trail, keyed by `email` string rather than `user_id`
    (a log entry must survive even if the referenced user is later
    deleted). `payload` is a native JSONB column -- the service layer works
    with plain Python dicts.

    Event set is deliberately narrow --
    Login/Failed/Lockout/Logout/Verified/PasswordReset are logged (see
    app.api.router_includes.auth for the call sites); Attempting/Validated/
    (Current|Other)DeviceLogout events are intentionally not logged
    (redundant with Failed/Login, or no multi-device-logout feature exists
    here at all).

    `fired_at` is TIMESTAMPTZ and stays Python-managed via
    datetime.now(UTC): it names the moment of the event, while
    `created_at`/`updated_at` (TIMESTAMPTZ, database DEFAULT now() and the
    shared set_updated_at() BEFORE UPDATE trigger, never assigned from
    Python) are the timestamp pair every table carries. Rows are never updated,
    so `updated_at` stays NULL."""

    __tablename__ = "auth_logs"
    __table_args__ = (
        Index(
            "auth_logs_email_event_fired_at_index",
            text("lower(email)"),
            "event",
            "fired_at",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event: Mapped[str] = mapped_column(auth_event_enum)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    email: Mapped[str | None]
    payload: Mapped[JsonObject | None] = mapped_column(JSONB())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
