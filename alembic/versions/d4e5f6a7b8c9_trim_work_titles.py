"""remove surrounding whitespace from ordinarium and proprium work titles

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-10-19 14:00:00.000000

Titles were stored exactly as typed, so "Ave Maria " sorted and searched
differently from "Ave Maria". Input is stripped from now on; this removes the
padding that is already stored. A title is only trimmed when no other work of
the same composer already holds the trimmed title, so the unique constraint on
(name, artist_id) cannot fail; such a title stays as it is.

The cleanup is not reversed on downgrade: the removed padding cannot be
reconstructed.
"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORK_TABLES = ("ordinariumworks", "propriumworks")


def _trimmed(column: str) -> str:
    return f"regexp_replace({column}, '^\\s+|\\s+$', '', 'g')"


def _trim_titles(table: str) -> str:
    # The table name is one of the two constants above, never input.
    return f"""
        UPDATE {table}
        SET name = {_trimmed(table + ".name")}
        WHERE name <> {_trimmed(table + ".name")}
          AND NOT EXISTS (
            SELECT 1 FROM {table} AS other
            WHERE other.id <> {table}.id
              AND other.artist_id = {table}.artist_id
              AND {_trimmed("other.name")} = {_trimmed(table + ".name")}
          )
    """  # noqa: S608


def upgrade() -> None:
    """Upgrade schema."""
    for table in WORK_TABLES:
        op.execute(_trim_titles(table))


def downgrade() -> None:
    """Downgrade schema."""
