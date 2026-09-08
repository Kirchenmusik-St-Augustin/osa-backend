"""drop sent_emails attachments column

Revision ID: 11ce36d7ccee
Revises: 82fa77b6e55b
Create Date: 2026-09-08 11:54:38.716254

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "11ce36d7ccee"
down_revision: str | Sequence[str] | None = "82fa77b6e55b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Verified dead: never read or written anywhere in the backend or
    # frontend (app.core.mailer's one SentEmail(...) construction site
    # never sets it) -- 0 of 16020 rows have a non-NULL value, dropped
    # outright rather than converted to jsonb.
    op.drop_column("sent_emails", "attachments")


def downgrade() -> None:
    """Downgrade schema."""
    # Lossless: the column was always NULL, so simply re-adding it
    # restores the exact prior schema shape.
    op.add_column("sent_emails", sa.Column("attachments", sa.String(), nullable=True))
