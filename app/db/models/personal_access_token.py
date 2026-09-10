from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, ForeignKey, Index, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PersonalAccessToken(Base):
    """Backs the JWT refresh flow by reusing legacy's `personal_access_tokens`
    table -- a dead, unused Sanctum artifact in Legacy (0 rows in prod).
    Legacy's generic/dead columns are repurposed: `token` holds the JWT-ID
    (jti), `abilities` (nullable TEXT, same as legacy) holds the refresh
    token hash, `expires_at` holds the refresh token's expiry.
    `refresh_token_hash` is a hybrid property so callers keep reading/
    writing a meaningful name while the underlying `abilities` column stays
    legacy-shaped.

    As of the polymorphy-redesign slice (2026-09), the former
    `tokenable_type`/`tokenable_id` polymorphic pair (Laravel's generic
    `morphTo`, byte-for-byte carried over from legacy in Phase 1) is
    replaced by a real `user_id` column with an ON DELETE CASCADE foreign
    key: `tokenable_type` never held anything but the constant "User" in
    this application (the JWT refresh flow only ever issues tokens to
    Users, and nothing in this codebase ever branched on it), so the
    generic polymorphic shape carried no actual behavior, only an
    unenforced reference. `user_id` was already the name every caller used
    for this column (see auth_service.py, app/api/deps.py) via a hybrid
    property aliasing the old `tokenable_id` -- it is now the real column
    name, and that alias is gone.

    Integer PK, not UUID: kept as part of the structural 1:1 transfer --
    UUID PKs are part of the not-yet-started full schema redesign.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger -- neither is assigned from
    Python anymore. `last_used_at`/`expires_at` are also TIMESTAMPTZ now
    (same slice) but stay Python-managed -- only their storage type
    changed."""

    __tablename__ = "personal_access_tokens"
    __table_args__ = (
        Index("personal_access_tokens_user_id_index", "user_id"),
        Index("personal_access_tokens_token_unique", "token", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]  # e.g. "session"
    token: Mapped[str]  # JWT-ID (jti)
    abilities: Mapped[str | None]  # repurposed: refresh token hash
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # refresh token expiry
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )

    @hybrid_property
    def refresh_token_hash(self) -> str | None:
        return self.abilities

    @refresh_token_hash.inplace.setter
    def _refresh_token_hash_setter(self, value: str | None) -> None:
        self.abilities = value
