"""rename order to sort_order

Revision ID: 2246345c4f5c
Revises: 521f1ba5e919
Create Date: 2026-09-07 13:02:18.070011

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2246345c4f5c"
down_revision: str | Sequence[str] | None = "521f1ba5e919"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `order` is a reserved SQL keyword, always requiring double-quoting on
# Postgres -- these seven tables are the only ones with an `order` column
# in the schema (five via the CoreelementColumns model mixin, plus Booking
# and Role, which declare it standalone). The Python ORM attribute name
# stays `order` on every model (mapped_column's explicit column-name
# argument), so no application code changes are needed alongside this
# migration.
_TABLES_WITH_ORDER_COLUMN = (
    "choirjobs",
    "instruments",
    "locations",
    "propriumelements",
    "voices",
    "bookings",
    "roles",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table_name in _TABLES_WITH_ORDER_COLUMN:
        op.alter_column(
            table_name,
            "order",
            new_column_name="sort_order",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table_name in _TABLES_WITH_ORDER_COLUMN:
        op.alter_column(
            table_name,
            "sort_order",
            new_column_name="order",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
