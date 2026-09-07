"""convert position_type to enum

Revision ID: 29a72b8fa4d7
Revises: fa9e6613c5c1
Create Date: 2026-09-08 10:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29a72b8fa4d7"
down_revision: str | Sequence[str] | None = "fa9e6613c5c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One shared 3-value type for all five tables below -- CREATE TYPE runs
# exactly once, every ALTER COLUMN references this same object/name.
position_type_enum = postgresql.ENUM(
    "instruments", "voices", "choirjobs", name="position_type", create_type=False
)

# The four tables where the shared 3-value enum is the ONLY restriction --
# their existing CHECK (identical to the enum's own domain) becomes fully
# redundant and is dropped for good. ordinariumwork_positions is
# deliberately excluded: its narrower 2-value CHECK
# (`IN ('instruments', 'voices')`, excluding 'choirjobs') still does real
# work even once the column is this 3-value enum. It does NOT need to be
# dropped/recreated at all -- verified empirically that Postgres
# automatically rewrites an existing CHECK constraint's expression across
# an ALTER COLUMN ... TYPE (both directions); the constraint survives this
# migration (and its downgrade) untouched, by name and by the exact two
# values it allows.
_UNRESTRICTED_TABLES = (
    "bookings",
    "booking_logs",
    "performance_positions",
    "user_positions",
)

_ALL_TABLES = (
    "bookings",
    "booking_logs",
    "ordinariumwork_positions",
    "performance_positions",
    "user_positions",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table_name in _UNRESTRICTED_TABLES:
        op.drop_constraint(
            f"{table_name}_position_type_check", table_name, type_="check"
        )
    position_type_enum.create(op.get_bind(), checkfirst=False)
    for table_name in _ALL_TABLES:
        op.alter_column(
            table_name,
            "position_type",
            existing_type=sa.String(),
            type_=position_type_enum,
            postgresql_using="position_type::position_type",
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table_name in _ALL_TABLES:
        op.alter_column(
            table_name,
            "position_type",
            existing_type=position_type_enum,
            type_=sa.String(),
            postgresql_using="position_type::varchar",
            existing_nullable=False,
        )
    position_type_enum.drop(op.get_bind(), checkfirst=False)
    for table_name in _UNRESTRICTED_TABLES:
        op.create_check_constraint(
            f"{table_name}_position_type_check",
            table_name,
            "position_type IN ('instruments', 'voices', 'choirjobs')",
        )
