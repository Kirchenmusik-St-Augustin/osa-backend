from datetime import datetime

from sqlalchemy import DateTime, Index
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

_TOKENABLE_TYPE = "User"


class PersonalAccessToken(Base):
    """Backs the JWT refresh flow by reusing legacy's `personal_access_tokens`
    table -- a dead, unused Sanctum artifact in Legacy (0 rows in prod, see
    project_osa_legacy_domain_map memory). User-confirmed 2026-07-31: this
    table stays byte-for-byte structurally identical to legacy (same
    columns, same nullability, same indexes, no FK -- legacy's own
    `tokenable_id` has none either, it's a polymorphic reference) so a
    fresh prod SQLite copy can always be dropped straight into dev without
    a schema patch, until the Phase 2 Postgres cutover. That means no new
    columns and no renames -- legacy's generic/dead columns are repurposed
    instead: `tokenable_type` always holds the constant "User" (never
    branched on, same as legacy's own dead code never branched on it),
    `tokenable_id` holds the user's id, `abilities` (nullable TEXT, same as
    legacy) holds the refresh token hash, `expires_at` holds the refresh
    token's expiry. `user_id`/`refresh_token_hash` are hybrid properties so
    callers keep reading/writing/querying meaningful names while the
    underlying row stays legacy-shaped. Integer PK, not UUID: Phase 1 keeps
    SQLite-appropriate IDs project-wide, UUID PKs are Phase-2-only
    (CLAUDE.md section 3, currently inactive)."""

    __tablename__ = "personal_access_tokens"
    __table_args__ = (
        Index(
            "personal_access_tokens_tokenable_type_tokenable_id_index",
            "tokenable_type",
            "tokenable_id",
        ),
        Index("personal_access_tokens_token_unique", "token", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tokenable_type: Mapped[str] = mapped_column(default=_TOKENABLE_TYPE)
    tokenable_id: Mapped[int]
    name: Mapped[str]  # e.g. "session"
    token: Mapped[str]  # JWT-ID (jti)
    abilities: Mapped[str | None]  # repurposed: refresh token hash
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime())
    # refresh token expiry
    expires_at: Mapped[datetime | None] = mapped_column(DateTime())
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())

    @hybrid_property
    def user_id(self) -> int:
        return self.tokenable_id

    @user_id.inplace.setter
    def _user_id_setter(self, value: int) -> None:
        self.tokenable_id = value

    @user_id.inplace.expression
    @classmethod
    def _user_id_expression(cls) -> Mapped[int]:
        return cls.tokenable_id

    @hybrid_property
    def refresh_token_hash(self) -> str | None:
        return self.abilities

    @refresh_token_hash.inplace.setter
    def _refresh_token_hash_setter(self, value: str | None) -> None:
        self.abilities = value
