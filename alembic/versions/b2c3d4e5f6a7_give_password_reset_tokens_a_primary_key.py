"""give password_reset_tokens a primary key and updated_at

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-17 09:10:00.000000

The table had neither a primary key nor a unique constraint on email, so two
concurrent reset requests for one address could leave two rows behind, which
makes the single-row lookup in the reset flow fail until the housekeeping job
purges them. Adds a UUIDv7 primary key, a unique constraint on email (its
index replaces the plain one) and the standard updated_at column maintained
by the set_updated_at() trigger.
"""

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Keep only the newest token per email before the unique constraint.
    op.execute(
        "DELETE FROM password_reset_tokens WHERE ctid IN ("
        "SELECT ctid FROM ("
        "SELECT ctid, row_number() OVER ("
        "PARTITION BY email ORDER BY created_at DESC NULLS LAST, ctid DESC"
        ") AS position FROM password_reset_tokens"
        ") AS ranked WHERE position > 1)"
    )
    op.add_column(
        "password_reset_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuidv7()"),
            nullable=False,
        ),
    )
    op.create_primary_key("password_reset_tokens_pkey", "password_reset_tokens", ["id"])
    op.create_unique_constraint(
        "password_reset_tokens_email_key", "password_reset_tokens", ["email"]
    )
    op.drop_index("password_resets_email_index", table_name="password_reset_tokens")
    op.add_column(
        "password_reset_tokens",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE TRIGGER set_updated_at BEFORE UPDATE ON password_reset_tokens "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER set_updated_at ON password_reset_tokens")
    op.drop_column("password_reset_tokens", "updated_at")
    op.create_index("password_resets_email_index", "password_reset_tokens", ["email"])
    op.drop_constraint(
        "password_reset_tokens_email_key", "password_reset_tokens", type_="unique"
    )
    op.drop_constraint(
        "password_reset_tokens_pkey", "password_reset_tokens", type_="primary"
    )
    op.drop_column("password_reset_tokens", "id")
