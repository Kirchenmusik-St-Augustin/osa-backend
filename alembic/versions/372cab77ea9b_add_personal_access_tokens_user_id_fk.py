"""add personal access tokens user id fk

Revision ID: 372cab77ea9b
Revises: 0d68c97c7933
Create Date: 2026-09-10 19:08:45.912441

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "372cab77ea9b"
down_revision: str | Sequence[str] | None = "0d68c97c7933"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    tokenable_type never held anything but the constant "User" in this
    application (the JWT refresh flow only ever issues tokens to Users,
    and nothing in this codebase ever branched on it) -- the generic
    polymorphic shape carried no actual behavior, only an unenforced
    reference. No backfill/orphan-check needed for the rename itself
    (RENAME COLUMN preserves every existing value); the FK below is where
    an actual orphaned tokenable_id (a personal_access_tokens row whose
    user no longer exists) would surface."""
    op.drop_index(
        "personal_access_tokens_tokenable_type_tokenable_id_index",
        table_name="personal_access_tokens",
    )
    op.alter_column("personal_access_tokens", "tokenable_id", new_column_name="user_id")
    op.drop_column("personal_access_tokens", "tokenable_type")
    op.create_index(
        "personal_access_tokens_user_id_index", "personal_access_tokens", ["user_id"]
    )
    op.create_foreign_key(
        "personal_access_tokens_user_id_fkey",
        "personal_access_tokens",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "personal_access_tokens_user_id_fkey",
        "personal_access_tokens",
        type_="foreignkey",
    )
    op.drop_index(
        "personal_access_tokens_user_id_index", table_name="personal_access_tokens"
    )
    # server_default backfills every existing row (the column never held
    # anything but "User" in practice, see upgrade()'s docstring) --
    # dropped again right after so the restored column matches the
    # original schema exactly (a Python-side ORM default only, no
    # server-side one, same as the baseline migration created it).
    op.add_column(
        "personal_access_tokens",
        sa.Column("tokenable_type", sa.String(), nullable=False, server_default="User"),
    )
    op.alter_column("personal_access_tokens", "tokenable_type", server_default=None)
    op.alter_column("personal_access_tokens", "user_id", new_column_name="tokenable_id")
    op.create_index(
        "personal_access_tokens_tokenable_type_tokenable_id_index",
        "personal_access_tokens",
        ["tokenable_type", "tokenable_id"],
    )
