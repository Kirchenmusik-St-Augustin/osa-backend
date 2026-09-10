"""replace position unique constraints and drop legacy columns

Revision ID: 0d68c97c7933
Revises: 7f5f0d1ca83e
Create Date: 2026-09-10 19:08:44.805703

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0d68c97c7933"
down_revision: str | Sequence[str] | None = "7f5f0d1ca83e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One shared 3-value type for the position_type column being dropped below
# -- matches the object 29a72b8fa4d7 (the migration that created it) used,
# needed here again to DROP TYPE at the end of upgrade() and recreate it in
# downgrade().
position_type_enum = postgresql.ENUM(
    "instruments", "voices", "choirjobs", name="position_type", create_type=False
)

# (table, old unique constraint name, old columns) -- the old (...,
# position_type, position_id)-based constraints, replaced below by the new
# (..., instrument_id, voice_id[, choirjob_id])-based ones. Constraint names
# taken verbatim from the live schema (Postgres's own default
# "<table>_<col>..._key" naming, several truncated to 63 bytes).
_OLD_UNIQUE_CONSTRAINTS: list[tuple[str, str, list[str]]] = [
    (
        "bookings",
        "bookings_performance_id_user_id_position_type_position_id_key",
        ["performance_id", "user_id", "position_type", "position_id"],
    ),
    (
        "performance_positions",
        "performance_positions_performance_id_position_type_position_key",
        ["performance_id", "position_type", "position_id"],
    ),
    (
        "ordinariumwork_positions",
        "ordinariumwork_positions_ordinariumwork_id_position_type_po_key",
        ["ordinariumwork_id", "position_type", "position_id"],
    ),
    (
        "user_positions",
        "user_positions_user_id_position_type_position_id_key",
        ["user_id", "position_type", "position_id"],
    ),
]

# (table, new constraint name, new columns) -- names match the explicit
# `name=` now given to each model's own UniqueConstraint
# (app/db/models/booking.py etc.), chosen explicitly rather than left to
# Postgres's own truncating default now that the column list is longer
# than before.
_NEW_UNIQUE_CONSTRAINTS: list[tuple[str, str, list[str]]] = [
    (
        "bookings",
        "bookings_position_unique",
        ["performance_id", "user_id", "instrument_id", "voice_id", "choirjob_id"],
    ),
    (
        "performance_positions",
        "performance_positions_position_unique",
        ["performance_id", "instrument_id", "voice_id", "choirjob_id"],
    ),
    (
        "ordinariumwork_positions",
        "ordinariumwork_positions_position_unique",
        ["ordinariumwork_id", "instrument_id", "voice_id"],
    ),
    (
        "user_positions",
        "user_positions_position_unique",
        ["user_id", "instrument_id", "voice_id", "choirjob_id"],
    ),
]

# (table, position_type value, new column) -- the exact reverse of
# 7f5f0d1ca83e's own _BACKFILL list, used by this migration's downgrade()
# to reconstruct position_type/position_id from whichever new column is set.
_BACKFILL: list[tuple[str, str, str]] = [
    ("bookings", "instruments", "instrument_id"),
    ("bookings", "voices", "voice_id"),
    ("bookings", "choirjobs", "choirjob_id"),
    ("booking_logs", "instruments", "instrument_id"),
    ("booking_logs", "voices", "voice_id"),
    ("booking_logs", "choirjobs", "choirjob_id"),
    ("performance_positions", "instruments", "instrument_id"),
    ("performance_positions", "voices", "voice_id"),
    ("performance_positions", "choirjobs", "choirjob_id"),
    ("ordinariumwork_positions", "instruments", "instrument_id"),
    ("ordinariumwork_positions", "voices", "voice_id"),
    ("user_positions", "instruments", "instrument_id"),
    ("user_positions", "voices", "voice_id"),
    ("user_positions", "choirjobs", "choirjob_id"),
]

# Tables that get BOTH a position_type and a position_id column back on
# downgrade (all five original polymorphic tables).
_TABLES = (
    "bookings",
    "booking_logs",
    "performance_positions",
    "ordinariumwork_positions",
    "user_positions",
)


def upgrade() -> None:
    """Upgrade schema."""
    for table, name, _columns in _OLD_UNIQUE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="unique")
    for table, name, columns in _NEW_UNIQUE_CONSTRAINTS:
        op.create_unique_constraint(
            name, table, columns, postgresql_nulls_not_distinct=True
        )

    # ordinariumwork_positions' old CHECK excluding 'choirjobs' becomes
    # redundant the instant position_type itself is dropped below -- the
    # exclusion is now structural (no choirjob_id column exists on this
    # table at all, see its own model), strictly stronger than the CHECK
    # it replaces.
    op.drop_constraint(
        "ordinariumwork_positions_position_type_check",
        "ordinariumwork_positions",
        type_="check",
    )

    for table in _TABLES:
        op.drop_column(table, "position_type")
        op.drop_column(table, "position_id")

    op.execute("DROP TYPE position_type")


def downgrade() -> None:
    """Downgrade schema.

    Fully lossless and mechanical (unlike some of the FK-hardening slice's
    own downgrades, which can legitimately fail on real historical NULL
    data): every value dropped here is still present on the instrument_id/
    voice_id/choirjob_id columns 7f5f0d1ca83e added, so it can always be
    reconstructed from them."""
    position_type_enum.create(op.get_bind(), checkfirst=False)

    for table in _TABLES:
        op.add_column(table, sa.Column("position_type", sa.String(), nullable=True))
        op.add_column(table, sa.Column("position_id", sa.Integer(), nullable=True))

    for table, old_value, new_column in _BACKFILL:
        # table/old_value/new_column come from the fixed literal list
        # above, not from any external input -- not an injection risk.
        op.execute(
            f"UPDATE {table} SET position_type = '{old_value}', "  # noqa: S608
            f"position_id = {new_column} WHERE {new_column} IS NOT NULL"
        )

    for table in _TABLES:
        op.alter_column(table, "position_id", nullable=False)
        op.alter_column(
            table,
            "position_type",
            existing_type=sa.String(),
            type_=position_type_enum,
            postgresql_using="position_type::position_type",
            nullable=False,
        )

    op.create_check_constraint(
        "ordinariumwork_positions_position_type_check",
        "ordinariumwork_positions",
        "position_type IN ('instruments', 'voices')",
    )

    for table, name, _columns in _NEW_UNIQUE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="unique")
    for table, name, columns in _OLD_UNIQUE_CONSTRAINTS:
        op.create_unique_constraint(name, table, columns)
