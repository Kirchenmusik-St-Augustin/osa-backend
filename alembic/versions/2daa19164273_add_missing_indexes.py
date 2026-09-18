"""add missing indexes

Revision ID: 2daa19164273
Revises: 6e1829d5f417
Create Date: 2026-09-07 12:56:11.624469

Plain (non-CONCURRENTLY) CREATE INDEX below -- each index briefly holds an
ACCESS EXCLUSIVE lock on its table for the duration of the build, blocking
concurrent writes. Acceptable at the low concurrency this application runs
under and at the table sizes when this migration first ran; not
retroactively rebuilt since a downtime-free swap gains nothing once an
index already exists. Future index migrations on tables expected to keep
growing substantially (booking_logs is the most likely candidate) should
build the index CONCURRENTLY instead, which Postgres only allows outside a
transaction block:

    def upgrade() -> None:
        with op.get_context().autocommit_block():
            op.create_index(
                "some_index",
                "some_table",
                ["some_column"],
                unique=False,
                postgresql_concurrently=True,
            )

(Alembic wraps each migration in a transaction by default -- CONCURRENTLY
raises "cannot run inside a transaction block" without autocommit_block().)
"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2daa19164273"
down_revision: str | Sequence[str] | None = "6e1829d5f417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "performances_schedule_index", "performances", ["schedule"], unique=False
    )
    op.create_index(
        "booking_logs_performance_id_user_id_created_at_index",
        "booking_logs",
        ["performance_id", "user_id", "created_at"],
        unique=False,
    )
    op.create_index("bookings_user_id_index", "bookings", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("bookings_user_id_index", table_name="bookings")
    op.drop_index(
        "booking_logs_performance_id_user_id_created_at_index",
        table_name="booking_logs",
    )
    op.drop_index("performances_schedule_index", table_name="performances")
