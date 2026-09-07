"""add missing indexes

Revision ID: 2daa19164273
Revises: 6e1829d5f417
Create Date: 2026-09-07 12:56:11.624469

"""

from typing import Sequence, Union

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
