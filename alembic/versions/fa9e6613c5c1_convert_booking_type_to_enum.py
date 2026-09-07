"""convert booking_type to enum

Revision ID: fa9e6613c5c1
Revises: 2246345c4f5c
Create Date: 2026-09-08 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa9e6613c5c1"
down_revision: str | Sequence[str] | None = "2246345c4f5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: this migration manages CREATE TYPE/DROP TYPE itself
# via this object's .create()/.drop() calls below -- the flag only matters
# for CREATE TABLE/DROP TABLE-triggered auto-management anyway (irrelevant
# here, this is a plain ALTER COLUMN on an existing table).
booking_type_enum = postgresql.ENUM(
    "book", "unbook", name="booking_type", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    # No table narrows booking_type further than this 2-value CHECK
    # already did (unlike position_type/ordinariumwork_positions in the
    # next migration) -- once the column is a 2-value ENUM the CHECK is
    # fully redundant, drop it for good rather than leave dead weight.
    op.drop_constraint("booking_logs_booking_type_check", "booking_logs", type_="check")
    booking_type_enum.create(op.get_bind(), checkfirst=False)
    op.alter_column(
        "booking_logs",
        "booking_type",
        existing_type=sa.String(),
        type_=booking_type_enum,
        postgresql_using="booking_type::booking_type",
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "booking_logs",
        "booking_type",
        existing_type=booking_type_enum,
        type_=sa.String(),
        postgresql_using="booking_type::varchar",
        existing_nullable=False,
    )
    booking_type_enum.drop(op.get_bind(), checkfirst=False)
    op.create_check_constraint(
        "booking_logs_booking_type_check",
        "booking_logs",
        "booking_type IN ('book', 'unbook')",
    )
