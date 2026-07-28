from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class AuthLog(Base):
    """Mirrors legacy `auth_logs` exactly (Phase 1 -- no renames, no schema
    changes). Write-only audit trail, keyed by `email` string rather than
    `user_id` (matches legacy -- a log entry must survive even if the
    referenced user is later deleted). No `created_at`/`updated_at`:
    `fired_at` is the only timestamp legacy ever had for this table.

    Event set is deliberately narrower than legacy's Laravel listeners
    (Login/Failed/Lockout/Logout/Verified/PasswordReset only) -- see
    feedback_sister_project_parity / the Schritt-2 plan for the "dropped
    Attempting/Validated/(Current|Other)DeviceLogout" reasoning."""

    __tablename__ = "auth_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str | None]
    fired_at: Mapped[datetime | None] = mapped_column(DateTime())
    ip_address: Mapped[str | None]
    user_agent: Mapped[str | None]
    email: Mapped[str | None]
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON())
