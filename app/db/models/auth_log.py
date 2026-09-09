from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.json_types import JsonObject
from app.db.database import Base


class AuthLog(Base):
    """Mirrors legacy `auth_logs` exactly (Phase 1 -- no renames, no schema
    changes). Write-only audit trail, keyed by `email` string rather than
    `user_id` (matches legacy -- a log entry must survive even if the
    referenced user is later deleted). No `created_at`/`updated_at`:
    `fired_at` is the only timestamp legacy ever had for this table.
    `payload` is a native JSONB column as of this slice (was the generic
    JSON type, which Postgres renders as `json` rather than `jsonb`) --
    the service layer already worked with plain Python dicts either way,
    so this is a pure storage-format tightening with no behavior change.

    Event set is deliberately narrower than legacy's 10 Laravel listeners --
    Login/Failed/Lockout/Logout/Verified/PasswordReset are kept (see
    app.api.router_includes.auth for the call sites), Attempting/Validated/
    (Current|Other)DeviceLogout are dropped as YAGNI (redundant with
    Failed/Login, or no multi-device-logout feature exists here at all).

    `fired_at` is TIMESTAMPTZ as of the TIMESTAMPTZ + audit-trigger
    hardening slice (2026-09) -- stays Python-managed via datetime.now(UTC)
    (this table has no created_at/updated_at pair, so no server_default/
    trigger applies here), only its storage type changed."""

    __tablename__ = "auth_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str | None]
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    email: Mapped[str | None]
    payload: Mapped[JsonObject | None] = mapped_column(JSONB())
