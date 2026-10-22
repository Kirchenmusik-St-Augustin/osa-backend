"""add created_at and updated_at to auth_logs and oauth2_bindings

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-20 15:00:00.000000

Every table carries created_at and updated_at, maintained like on all other
tables: created_at by DEFAULT now(), updated_at by the set_updated_at()
trigger. The rows that exist already get the time of the event they record
(fired_at, bound_at) as their created_at instead of the time of this
migration, so the new column does not claim they were created today.
"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> the column that already holds the time the row came into being
_TABLES: dict[str, str] = {"auth_logs": "fired_at", "oauth2_bindings": "bound_at"}


def upgrade() -> None:
    """Upgrade schema."""
    for table, event_column in _TABLES.items():
        op.add_column(
            table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.execute(f"UPDATE {table} SET created_at = {event_column}")  # noqa: S608
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        )
        op.add_column(
            table, sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.execute(
            f"CREATE TRIGGER set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER set_updated_at ON {table}")
        op.drop_column(table, "updated_at")
        op.drop_column(table, "created_at")
