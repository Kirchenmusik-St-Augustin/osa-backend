import uuid
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.json_types import JsonObject
from app.db.database import Base
from app.db.uuid_pk import uuid_pk


class AuthLog(Base):
    """Write-only audit trail, keyed by `email` string rather than `user_id`
    (a log entry must survive even if the referenced user is later
    deleted). No `created_at`/`updated_at`: `fired_at` is the only
    timestamp of this table. `payload` is a native JSONB column -- the
    service layer works with plain Python dicts.

    Event set is deliberately narrow --
    Login/Failed/Lockout/Logout/Verified/PasswordReset are logged (see
    app.api.router_includes.auth for the call sites); Attempting/Validated/
    (Current|Other)DeviceLogout events are intentionally not logged
    (redundant with Failed/Login, or no multi-device-logout feature exists
    here at all).

    `fired_at` is TIMESTAMPTZ and stays Python-managed via
    datetime.now(UTC) (this table has no created_at/updated_at pair, so no
    server_default/trigger applies here)."""

    __tablename__ = "auth_logs"

    id: Mapped[uuid.UUID] = uuid_pk()
    event: Mapped[str | None]
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    email: Mapped[str | None]
    payload: Mapped[JsonObject | None] = mapped_column(JSONB())
