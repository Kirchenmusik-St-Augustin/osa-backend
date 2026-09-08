"""convert auth_logs payload to jsonb

Revision ID: 82fa77b6e55b
Revises: b61659594529
Create Date: 2026-09-08 11:54:31.102938

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "82fa77b6e55b"
down_revision: str | Sequence[str] | None = "b61659594529"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # json -> jsonb is a lossless, always-valid native Postgres cast (the
    # source column is already a validated `json` type, unlike
    # request_logs' varchar-holding-JSON-text columns in the previous
    # migration) -- no pre-migration data verification needed here.
    op.alter_column(
        "auth_logs",
        "payload",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        postgresql_using="payload::jsonb",
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "auth_logs",
        "payload",
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        postgresql_using="payload::json",
        existing_nullable=True,
    )
