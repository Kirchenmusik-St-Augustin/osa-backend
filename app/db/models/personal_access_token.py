from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PersonalAccessToken(Base):
    """Revocable server-side session, backing the JWT refresh flow. No
    legacy equivalent (Legacy's own `personal_access_tokens` table is a
    dead, unused Sanctum artifact -- see project_osa_legacy_domain_map
    memory) -- this table replaces it under the same name (1:1 vb-api
    convention, User-confirmed 2026-07-28). Integer PK, not UUID: Phase 1
    keeps SQLite-appropriate IDs project-wide, UUID PKs are Phase-2-only
    (CLAUDE.md section 3, currently inactive)."""

    __tablename__ = "personal_access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE")
    )
    name: Mapped[str]  # e.g. "session"
    token: Mapped[str] = mapped_column(unique=True, index=True)  # JWT-ID (jti)
    refresh_token_hash: Mapped[str | None]
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
