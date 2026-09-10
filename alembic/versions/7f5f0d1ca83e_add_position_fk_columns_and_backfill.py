"""add position fk columns and backfill

Revision ID: 7f5f0d1ca83e
Revises: 486c6e00cbd4
Create Date: 2026-09-10 19:08:43.598877

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f5f0d1ca83e"
down_revision: str | Sequence[str] | None = "486c6e00cbd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The five tables carrying the old position_type (native enum) +
# position_id (plain int, no FK) polymorphic pair, and which of the three
# new FK columns each one gets. ordinariumwork_positions only ever gets
# two -- its domain structurally excludes choirjobs (see its own model).
_NEW_COLUMNS: list[tuple[str, str]] = [
    ("bookings", "instrument_id"),
    ("bookings", "voice_id"),
    ("bookings", "choirjob_id"),
    ("booking_logs", "instrument_id"),
    ("booking_logs", "voice_id"),
    ("booking_logs", "choirjob_id"),
    ("performance_positions", "instrument_id"),
    ("performance_positions", "voice_id"),
    ("performance_positions", "choirjob_id"),
    ("ordinariumwork_positions", "instrument_id"),
    ("ordinariumwork_positions", "voice_id"),
    ("user_positions", "instrument_id"),
    ("user_positions", "voice_id"),
    ("user_positions", "choirjob_id"),
]

# (table, old position_type value, new column) -- one UPDATE per row,
# copying the old generic position_id into whichever new column matches
# its old position_type. Written this way (rather than a single CASE
# expression) so each statement stays a trivial, individually-reviewable
# single-column copy.
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

# (table, CHECK expression, constraint name) -- verifies the backfill above
# was exhaustive and exclusive: exactly one of the new columns is set on
# every row. num_nonnulls() is a built-in Postgres function; only
# ordinariumwork_positions gets the two-argument form.
_CHECKS: list[tuple[str, str, str]] = [
    (
        "bookings",
        "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
        "bookings_position_exactly_one_check",
    ),
    (
        "booking_logs",
        "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
        "booking_logs_position_exactly_one_check",
    ),
    (
        "performance_positions",
        "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
        "performance_positions_position_exactly_one_check",
    ),
    (
        "ordinariumwork_positions",
        "num_nonnulls(instrument_id, voice_id) = 1",
        "ordinariumwork_positions_position_exactly_one_check",
    ),
    (
        "user_positions",
        "num_nonnulls(instrument_id, voice_id, choirjob_id) = 1",
        "user_positions_position_exactly_one_check",
    ),
]

# column name -> referent lookup table. RESTRICT uniformly: an Instrument/
# Voice/Choirjob is never actually hard-deleted in this system (its
# `active` flag exists specifically so it never has to be), so this is a
# defense-in-depth backstop, not a live behavioral constraint (see
# app.db.models.position_columns_mixin's docstring).
_REFERENT_BY_COLUMN: dict[str, str] = {
    "instrument_id": "instruments",
    "voice_id": "voices",
    "choirjob_id": "choirjobs",
}


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _NEW_COLUMNS:
        op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))

    for table, old_value, new_column in _BACKFILL:
        # table/old_value/new_column come from the fixed literal list
        # above, not from any external input -- not an injection risk.
        op.execute(
            f"UPDATE {table} SET {new_column} = position_id "  # noqa: S608
            f"WHERE position_type = '{old_value}'"
        )

    for table, expression, name in _CHECKS:
        op.create_check_constraint(name, table, expression)

    # This is the step that fails loudly if any orphaned position_id
    # exists (a position_id with no matching row in instruments/voices/
    # choirjobs) -- deliberately no automatic orphan cleanup here (unlike
    # 9895db228a15's SET NULL cleanup): silently nulling a historical
    # booking's position would itself violate "no orphaned records" in a
    # different way, by erasing which instrument/voice/choirjob a
    # historical row was actually for. A real orphan must be investigated
    # manually, not papered over by a migration.
    for table, column in _NEW_COLUMNS:
        referent = _REFERENT_BY_COLUMN[column]
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            referent,
            [column],
            ["id"],
            ondelete="RESTRICT",
        )

    for table, column in _NEW_COLUMNS:
        op.create_index(f"{table}_{column}_index", table, [column])


def downgrade() -> None:
    """Downgrade schema.

    Fully lossless and mechanical: the old position_type/position_id
    columns are untouched by this migration (they're only dropped in the
    following one), so this just removes what was added here -- no
    orphan-style data-loss risk like some of the FK-hardening slice's own
    downgrades."""
    for table, column in reversed(_NEW_COLUMNS):
        op.drop_index(f"{table}_{column}_index", table_name=table)

    for table, column in reversed(_NEW_COLUMNS):
        op.drop_constraint(f"{table}_{column}_fkey", table, type_="foreignkey")

    for table, _expression, name in reversed(_CHECKS):
        op.drop_constraint(name, table, type_="check")

    for table, column in reversed(_NEW_COLUMNS):
        op.drop_column(table, column)
