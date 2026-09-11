"""add uuid bridge columns for pk and fk migration

Revision ID: ad392756fe88
Revises: 1f1716b2a4f1
Create Date: 2026-09-10 22:16:40.560702

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ad392756fe88"
down_revision: str | Sequence[str] | None = "1f1716b2a4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase A of the UUIDv7 primary-key migration (additive, zero-downtime --
# the still-running application never reads or writes any column added
# here). Every table with an integer primary key gets a parallel
# `id_uuid` column; every foreign key column gets a parallel `<column>
# _uuid` column pointing at its parent's `id_uuid`. The actual cutover
# (dropping the old integer id/*_id columns, renaming these into their
# place, recreating every constraint against them) is a separate,
# maintenance-window migration -- see that migration's own module
# docstring for why this is split into two steps.
#
# `password_reset_tokens` is the one table with no integer primary key
# at all (its PK is `email`, mirroring legacy's own columnless-id shape)
# -- excluded from `_PK_TABLES`, and no table has a foreign key into it.
_PK_TABLES: list[str] = [
    "artists",
    "auth_logs",
    "booking_logs",
    "bookings",
    "booking_requests",
    "choirjobs",
    "client_user_agents",
    "fees",
    "instruments",
    "locations",
    "oauth2_bindings",
    "ordinariumworks",
    "ordinariumwork_positions",
    "performances",
    "performance_positions",
    "performance_proprium",
    "performance_rehearsals",
    "personal_access_tokens",
    "propriumelements",
    "propriumworks",
    "request_logs",
    "roles",
    "scores",
    "sent_emails",
    "shorturls",
    "user_positions",
    "users",
    "user_roles",
    "voices",
]

# (table, foreign-key column, referenced table) -- the complete physical
# foreign-key-column catalog (38 columns), including every column that
# fans out from a shared mixin (PositionColumns' instrument_id/voice_id/
# choirjob_id on bookings/booking_logs/performance_positions/
# user_positions; RepertoireWorkColumns' artist_id on ordinariumworks/
# propriumworks) written out per physical table rather than per mixin,
# so this list is a flat, reviewable catalog matching exactly what
# `\d <table>` shows on the live database.
_FK_COLUMNS: list[tuple[str, str, str]] = [
    ("booking_logs", "performance_id", "performances"),
    ("booking_logs", "user_id", "users"),
    ("booking_logs", "instrument_id", "instruments"),
    ("booking_logs", "voice_id", "voices"),
    ("booking_logs", "choirjob_id", "choirjobs"),
    ("booking_requests", "performance_id", "performances"),
    ("booking_requests", "user_id", "users"),
    ("bookings", "performance_id", "performances"),
    ("bookings", "user_id", "users"),
    ("bookings", "instrument_id", "instruments"),
    ("bookings", "voice_id", "voices"),
    ("bookings", "choirjob_id", "choirjobs"),
    ("oauth2_bindings", "local_id", "users"),
    ("ordinariumwork_positions", "ordinariumwork_id", "ordinariumworks"),
    ("ordinariumwork_positions", "instrument_id", "instruments"),
    ("ordinariumwork_positions", "voice_id", "voices"),
    ("ordinariumworks", "artist_id", "artists"),
    ("performance_positions", "performance_id", "performances"),
    ("performance_positions", "instrument_id", "instruments"),
    ("performance_positions", "voice_id", "voices"),
    ("performance_positions", "choirjob_id", "choirjobs"),
    ("performance_proprium", "performance_id", "performances"),
    ("performance_proprium", "propriumelement_id", "propriumelements"),
    ("performance_proprium", "propriumwork_id", "propriumworks"),
    ("performance_rehearsals", "performance_id", "performances"),
    ("performances", "location_id", "locations"),
    ("performances", "ordinariumwork_id", "ordinariumworks"),
    ("performances", "artist_id", "artists"),
    ("personal_access_tokens", "user_id", "users"),
    ("propriumworks", "artist_id", "artists"),
    ("request_logs", "client_user_agent_id", "client_user_agents"),
    ("request_logs", "user_id", "users"),
    ("user_positions", "user_id", "users"),
    ("user_positions", "instrument_id", "instruments"),
    ("user_positions", "voice_id", "voices"),
    ("user_positions", "choirjob_id", "choirjobs"),
    ("user_roles", "user_id", "users"),
    ("user_roles", "role_id", "roles"),
]


def upgrade() -> None:
    """Upgrade schema."""
    # `ADD COLUMN ... DEFAULT uuidv7()` on Postgres forces a full table
    # rewrite because the default expression is volatile (a constant
    # default would use the PG11+ fast-default metadata-only path
    # instead) -- but that rewrite is exactly what backfills every
    # existing row with its own distinct uuidv7() value in the same
    # statement, verified empirically before writing this migration.
    # No separate backfill UPDATE is needed for the PK bridge columns.
    for table in _PK_TABLES:
        op.add_column(
            table,
            sa.Column(
                "id_uuid",
                sa.Uuid(),
                nullable=False,
                server_default=sa.text("uuidv7()"),
            ),
        )
        op.create_index(f"{table}_id_uuid_key", table, ["id_uuid"], unique=True)

    # Foreign-key bridge columns can only be backfilled by joining
    # against the parent's id_uuid, so every _PK_TABLES column above
    # must already exist and be populated before this loop runs.
    for table, column, referent in _FK_COLUMNS:
        op.add_column(table, sa.Column(f"{column}_uuid", sa.Uuid(), nullable=True))
        # table/column/referent come from the fixed literal list above,
        # not from any external input -- not an injection risk.
        op.execute(
            f"UPDATE {table} SET {column}_uuid = {referent}.id_uuid "  # noqa: S608
            f"FROM {referent} WHERE {table}.{column} = {referent}.id"
        )


def downgrade() -> None:
    """Downgrade schema.

    Fully lossless and mechanical: this migration is purely additive
    (the running application never reads or writes any column added
    here), so removing them is a plain, safe reversal -- unlike the
    cutover migration that follows this one, which is deliberately
    irreversible once live traffic depends on it."""
    for table, column, _referent in reversed(_FK_COLUMNS):
        op.drop_column(table, f"{column}_uuid")

    for table in reversed(_PK_TABLES):
        op.drop_index(f"{table}_id_uuid_key", table_name=table)
        op.drop_column(table, "id_uuid")
