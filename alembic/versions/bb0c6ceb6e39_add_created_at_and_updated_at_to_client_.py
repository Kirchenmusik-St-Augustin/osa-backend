"""add created_at and updated_at to client_user_agents

Revision ID: bb0c6ceb6e39
Revises: c5d4bc206313
Create Date: 2026-09-18 11:05:39.184935

"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb0c6ceb6e39"
down_revision: str | Sequence[str] | None = "c5d4bc206313"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "client_user_agents",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.add_column(
        "client_user_agents",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE TRIGGER set_updated_at "
        "BEFORE UPDATE ON client_user_agents "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER set_updated_at ON client_user_agents;")
    op.drop_column("client_user_agents", "updated_at")
    op.drop_column("client_user_agents", "created_at")
