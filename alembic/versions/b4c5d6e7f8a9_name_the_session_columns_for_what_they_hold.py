"""name the session columns for what they hold, drop the unused ones

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-20 21:00:00.000000

The session table came with generic column names that the application filled
with something else: `abilities` holds the hash of the refresh secret and
`token` the identifier of the JWT. A column whose name says one thing and
whose content is another is how a secret ends up unmasked. They are called
refresh_token_hash and jti now. `name` always held the word "session" and
`expires_at` was never read or written (the lifetime of a session is computed
from created_at), so both are dropped. Production was checked beforehand: all
523 sessions carry a hash, the name "session" and no expiry. A rename keeps
every live session valid.
"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "personal_access_tokens"


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(_TABLE, "abilities", new_column_name="refresh_token_hash")
    op.alter_column(_TABLE, "token", new_column_name="jti")
    op.execute(
        "ALTER INDEX personal_access_tokens_token_unique "
        "RENAME TO personal_access_tokens_jti_unique"
    )
    op.drop_column(_TABLE, "name")
    op.drop_column(_TABLE, "expires_at")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        _TABLE, sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "name", sa.String(), nullable=False, server_default=sa.text("'session'")
        ),
    )
    op.alter_column(_TABLE, "name", server_default=None)
    op.execute(
        "ALTER INDEX personal_access_tokens_jti_unique "
        "RENAME TO personal_access_tokens_token_unique"
    )
    op.alter_column(_TABLE, "jti", new_column_name="token")
    op.alter_column(_TABLE, "refresh_token_hash", new_column_name="abilities")
