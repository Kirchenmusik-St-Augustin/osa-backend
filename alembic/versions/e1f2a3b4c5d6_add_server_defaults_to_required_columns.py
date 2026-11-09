"""add server defaults to required columns that only had a Python default

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-20 18:00:00.000000

These columns are NOT NULL and the application always fills them, but a
writer that is not this ORM (a restore script, an administrator at psql, a
later service) had to know and supply each one, and a forgotten security flag
failed with a NOT NULL error. The defaults the application uses now belong to
the table definition as well. Existing rows are unaffected.
"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFAULTS: list[tuple[str, str, sa.sql.elements.ColumnElement[object]]] = [
    ("users", "auth_locked", sa.false()),
    ("users", "administrator", sa.false()),
    ("artists", "composer", sa.false()),
    ("artists", "conductor", sa.false()),
    ("instruments", "active", sa.true()),
    ("voices", "active", sa.true()),
    ("choirjobs", "active", sa.true()),
    ("ordinariumworks", "demanding", sa.false()),
    ("propriumworks", "demanding", sa.false()),
    ("shorturls", "counter", sa.text("0")),
    ("performances", "choirjob_defaultfee", sa.text("35")),
    ("performances", "instrument_defaultfee", sa.text("60")),
    ("performances", "voice_defaultfee", sa.text("110")),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, default in _DEFAULTS:
        op.alter_column(table, column, server_default=default)


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, _default in reversed(_DEFAULTS):
        op.alter_column(table, column, server_default=None)
