"""cutover to uuid primary and foreign keys

Revision ID: b70c44b3cf7b
Revises: ad392756fe88
Create Date: 2026-09-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b70c44b3cf7b"
down_revision: str | Sequence[str] | None = "ad392756fe88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Phase B of the UUIDv7 primary-key migration -- the atomic cutover this
# project's application code has been waiting for since the previous
# (purely additive) migration. This is the one migration in the whole
# UUIDv7 effort that needs a real maintenance window: the running
# application (still expecting integer ids) and the post-cutover
# application (expecting UUIDs) cannot both be correct against the same
# schema at the same time, so this migration and the matching backend/
# frontend deploy must land together, traffic stopped.
#
# Every catalog below (`_PK_TABLES`, `_FK_COLUMNS`, `_UNIQUE_CONSTRAINTS`,
# `_CHECK_CONSTRAINTS`, `_PLAIN_INDEXES`) is transcribed directly from a
# live `pg_constraint`/`pg_index` dump of the schema the previous
# migration produced, not re-derived from the ORM models -- every name,
# `ondelete` rule and nullability below is exactly what already exists in
# production, carried forward unchanged.
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

# (table, column, referent table, ON DELETE rule, was the old column
# NOT NULL). Every FK constraint below is named `<table>_<column>_fkey`
# on the live database, without exception -- the loops below rely on
# that regularity instead of a separate name column.
_FK_COLUMNS: list[tuple[str, str, str, str, bool]] = [
    ("booking_logs", "performance_id", "performances", "SET NULL", False),
    ("booking_logs", "user_id", "users", "SET NULL", False),
    ("booking_logs", "instrument_id", "instruments", "RESTRICT", False),
    ("booking_logs", "voice_id", "voices", "RESTRICT", False),
    ("booking_logs", "choirjob_id", "choirjobs", "RESTRICT", False),
    ("booking_requests", "performance_id", "performances", "RESTRICT", True),
    ("booking_requests", "user_id", "users", "CASCADE", True),
    ("bookings", "performance_id", "performances", "RESTRICT", True),
    ("bookings", "user_id", "users", "RESTRICT", True),
    ("bookings", "instrument_id", "instruments", "RESTRICT", False),
    ("bookings", "voice_id", "voices", "RESTRICT", False),
    ("bookings", "choirjob_id", "choirjobs", "RESTRICT", False),
    ("oauth2_bindings", "local_id", "users", "CASCADE", True),
    (
        "ordinariumwork_positions",
        "ordinariumwork_id",
        "ordinariumworks",
        "CASCADE",
        True,
    ),
    ("ordinariumwork_positions", "instrument_id", "instruments", "RESTRICT", False),
    ("ordinariumwork_positions", "voice_id", "voices", "RESTRICT", False),
    ("ordinariumworks", "artist_id", "artists", "RESTRICT", True),
    ("performance_positions", "performance_id", "performances", "CASCADE", True),
    ("performance_positions", "instrument_id", "instruments", "RESTRICT", False),
    ("performance_positions", "voice_id", "voices", "RESTRICT", False),
    ("performance_positions", "choirjob_id", "choirjobs", "RESTRICT", False),
    ("performance_proprium", "performance_id", "performances", "CASCADE", True),
    (
        "performance_proprium",
        "propriumelement_id",
        "propriumelements",
        "RESTRICT",
        True,
    ),
    ("performance_proprium", "propriumwork_id", "propriumworks", "RESTRICT", True),
    ("performance_rehearsals", "performance_id", "performances", "CASCADE", True),
    ("performances", "location_id", "locations", "RESTRICT", True),
    ("performances", "ordinariumwork_id", "ordinariumworks", "RESTRICT", True),
    ("performances", "artist_id", "artists", "RESTRICT", False),
    ("personal_access_tokens", "user_id", "users", "CASCADE", True),
    ("propriumworks", "artist_id", "artists", "RESTRICT", True),
    ("request_logs", "client_user_agent_id", "client_user_agents", "SET NULL", False),
    ("request_logs", "user_id", "users", "SET NULL", False),
    ("user_positions", "user_id", "users", "CASCADE", True),
    ("user_positions", "instrument_id", "instruments", "RESTRICT", False),
    ("user_positions", "voice_id", "voices", "RESTRICT", False),
    ("user_positions", "choirjob_id", "choirjobs", "RESTRICT", False),
    ("user_roles", "user_id", "users", "CASCADE", True),
    ("user_roles", "role_id", "roles", "RESTRICT", True),
]

# (table, constraint name, columns, NULLS NOT DISTINCT). The five
# "exactly one position column set" arcs from the polymorphy-redesign
# migration all fall in this list.
_UNIQUE_CONSTRAINTS: list[tuple[str, str, tuple[str, ...], bool]] = [
    (
        "booking_requests",
        "booking_requests_performance_id_user_id_key",
        ("performance_id", "user_id"),
        False,
    ),
    (
        "bookings",
        "bookings_performance_id_user_id_key",
        ("performance_id", "user_id"),
        False,
    ),
    (
        "bookings",
        "bookings_position_unique",
        ("performance_id", "user_id", "instrument_id", "voice_id", "choirjob_id"),
        True,
    ),
    (
        "ordinariumwork_positions",
        "ordinariumwork_positions_position_unique",
        ("ordinariumwork_id", "instrument_id", "voice_id"),
        True,
    ),
    (
        "ordinariumworks",
        "ordinariumworks_name_artist_id_key",
        ("name", "artist_id"),
        False,
    ),
    (
        "performance_positions",
        "performance_positions_position_unique",
        ("performance_id", "instrument_id", "voice_id", "choirjob_id"),
        True,
    ),
    (
        "performance_proprium",
        "performance_proprium_performance_id_propriumelement_id_key",
        ("performance_id", "propriumelement_id"),
        False,
    ),
    (
        "performance_rehearsals",
        "performance_rehearsals_performance_id_schedule_key",
        ("performance_id", "schedule"),
        False,
    ),
    (
        "propriumworks",
        "propriumworks_name_artist_id_key",
        ("name", "artist_id"),
        False,
    ),
    (
        "user_positions",
        "user_positions_position_unique",
        ("user_id", "instrument_id", "voice_id", "choirjob_id"),
        True,
    ),
    (
        "user_roles",
        "user_roles_user_id_role_id_key",
        ("user_id", "role_id"),
        False,
    ),
]

# The five exclusive-arc CHECKs from the polymorphy-redesign migration --
# `num_nonnulls(...) = 1` only tests NULL-ness, so it is semantically
# identical whether it names the int or the uuid sibling columns.
_CHECK_CONSTRAINTS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "booking_logs",
        "booking_logs_position_exactly_one_check",
        ("instrument_id", "voice_id", "choirjob_id"),
    ),
    (
        "bookings",
        "bookings_position_exactly_one_check",
        ("instrument_id", "voice_id", "choirjob_id"),
    ),
    (
        "ordinariumwork_positions",
        "ordinariumwork_positions_position_exactly_one_check",
        ("instrument_id", "voice_id"),
    ),
    (
        "performance_positions",
        "performance_positions_position_exactly_one_check",
        ("instrument_id", "voice_id", "choirjob_id"),
    ),
    (
        "user_positions",
        "user_positions_position_exactly_one_check",
        ("instrument_id", "voice_id", "choirjob_id"),
    ),
]

# Plain (non-unique) btree indexes whose column list includes at least
# one id column -- indexes that don't (performances_schedule_index,
# password_resets_email_index) are untouched by this migration.
_PLAIN_INDEXES: list[tuple[str, str, tuple[str, ...]]] = [
    ("booking_logs", "booking_logs_choirjob_id_index", ("choirjob_id",)),
    ("booking_logs", "booking_logs_instrument_id_index", ("instrument_id",)),
    (
        "booking_logs",
        "booking_logs_performance_id_user_id_created_at_index",
        ("performance_id", "user_id", "created_at"),
    ),
    ("booking_logs", "booking_logs_voice_id_index", ("voice_id",)),
    ("bookings", "bookings_choirjob_id_index", ("choirjob_id",)),
    ("bookings", "bookings_instrument_id_index", ("instrument_id",)),
    ("bookings", "bookings_user_id_index", ("user_id",)),
    ("bookings", "bookings_voice_id_index", ("voice_id",)),
    (
        "ordinariumwork_positions",
        "ordinariumwork_positions_instrument_id_index",
        ("instrument_id",),
    ),
    (
        "ordinariumwork_positions",
        "ordinariumwork_positions_voice_id_index",
        ("voice_id",),
    ),
    (
        "performance_positions",
        "performance_positions_choirjob_id_index",
        ("choirjob_id",),
    ),
    (
        "performance_positions",
        "performance_positions_instrument_id_index",
        ("instrument_id",),
    ),
    ("performance_positions", "performance_positions_voice_id_index", ("voice_id",)),
    ("personal_access_tokens", "personal_access_tokens_user_id_index", ("user_id",)),
    ("user_positions", "user_positions_choirjob_id_index", ("choirjob_id",)),
    ("user_positions", "user_positions_instrument_id_index", ("instrument_id",)),
    ("user_positions", "user_positions_voice_id_index", ("voice_id",)),
]


def _bridge_column(column: str) -> str:
    return f"{column}_uuid"


def _legacy_column(column: str) -> str:
    return f"{column}_legacy_int"


_FK_COLUMN_NAMES: frozenset[tuple[str, str]] = frozenset(
    (table, column) for table, column, _referent, _ondelete, _not_null in _FK_COLUMNS
)


def _is_id_column(table: str, column: str) -> bool:
    """True if `column` on `table` is one of the FK columns this
    migration bridges -- used to tell which entries of a mixed column
    list (a composite UNIQUE/index spanning an id column and a plain
    business column, e.g. `(name, artist_id)` or `(performance_id,
    schedule)`) need the `_uuid` suffix and which don't."""
    return (table, column) in _FK_COLUMN_NAMES


def _final_backfill() -> None:
    """Step 1: close the one gap the previous migration's own docstring
    calls out -- rows the still-running (pre-cutover) application
    inserted or repointed between that migration's deploy and this
    one's, whose FK bridge column was never backfilled because it didn't
    exist yet at insert time. Idempotent (re-running it changes nothing
    once every row is already backfilled), and the application is
    stopped for the rest of this migration, so nothing can add a new
    unbackfilled row underneath it."""
    for table, column, referent, _ondelete, _not_null in _FK_COLUMNS:
        bridge = _bridge_column(column)
        # table/column/referent/bridge all come from the fixed literal
        # catalog above, not from any external input -- not an injection
        # risk.
        op.execute(
            f"UPDATE {table} SET {bridge} = {referent}.id_uuid "  # noqa: S608
            f"FROM {referent} "
            f"WHERE {table}.{column} = {referent}.id AND {table}.{bridge} IS NULL"
        )


def _assert_backfill_complete() -> None:
    """Step 2: integrity gate -- refuse every destructive step below
    unless every bridge column is fully and correctly populated. A loud
    RuntimeError (not a silent assert, which `python -O` could strip) so
    a broken backfill aborts here, before anything is dropped."""
    connection = op.get_bind()
    for table in _PK_TABLES:
        missing = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE id_uuid IS NULL")  # noqa: S608
        ).scalar_one()
        if missing:
            msg = f"{table}: {missing} row(s) still have a NULL id_uuid."
            raise RuntimeError(msg)
    for table, column, _referent, _ondelete, _not_null in _FK_COLUMNS:
        bridge = _bridge_column(column)
        missing = connection.execute(
            sa.text(
                f"SELECT count(*) FROM {table} "  # noqa: S608
                f"WHERE {column} IS NOT NULL AND {bridge} IS NULL"
            )
        ).scalar_one()
        if missing:
            msg = (
                f"{table}.{bridge}: {missing} row(s) with a non-null {column} "
                "still have a NULL backfilled uuid."
            )
            raise RuntimeError(msg)


def _drop_old_constraints_and_indexes() -> None:
    """Steps 3-6: drop every constraint/index referencing an old integer
    id column, in dependency order (FKs before the PK they may point at,
    everything before the PK drop in the next step)."""
    for table, column, _referent, _ondelete, _not_null in _FK_COLUMNS:
        op.drop_constraint(f"{table}_{column}_fkey", table, type_="foreignkey")
    for table, name, _columns, _nulls_not_distinct in _UNIQUE_CONSTRAINTS:
        op.drop_constraint(name, table, type_="unique")
    for table, name, _columns in _CHECK_CONSTRAINTS:
        op.drop_constraint(name, table, type_="check")
    for table, name, _columns in _PLAIN_INDEXES:
        op.drop_index(name, table_name=table)


def _promote_uuid_primary_keys() -> None:
    """Steps 7-9: drop every old integer PRIMARY KEY (safe now --
    _drop_old_constraints_and_indexes already removed everything that
    referenced it), drop the Phase-A bridge unique index, then promote
    id_uuid to the real PRIMARY KEY under the original constraint
    name."""
    for table in _PK_TABLES:
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
    for table in _PK_TABLES:
        op.drop_index(f"{table}_id_uuid_key", table_name=table)
    for table in _PK_TABLES:
        op.create_primary_key(f"{table}_pkey", table, ["id_uuid"])


def _recreate_constraints_and_indexes() -> None:
    """Steps 10-14: restore each FK bridge column's original NOT
    NULL-ness (it was added nullable in the previous migration
    regardless of the target's own nullability, since the join backfill
    can't set what isn't there yet), then recreate every FK/UNIQUE/CHECK
    constraint and plain index against the uuid columns, each under its
    original name."""
    for table, column, _referent, _ondelete, not_null in _FK_COLUMNS:
        if not_null:
            op.alter_column(table, _bridge_column(column), nullable=False)

    for table, column, referent, ondelete, _not_null in _FK_COLUMNS:
        op.create_foreign_key(
            f"{table}_{column}_fkey",
            table,
            referent,
            [_bridge_column(column)],
            ["id_uuid"],
            ondelete=ondelete,
        )

    for table, name, columns, nulls_not_distinct in _UNIQUE_CONSTRAINTS:
        bridged = [_bridge_column(c) if _is_id_column(table, c) else c for c in columns]
        op.create_unique_constraint(
            name,
            table,
            bridged,
            postgresql_nulls_not_distinct=nulls_not_distinct,
        )

    for table, name, columns in _CHECK_CONSTRAINTS:
        bridged_list = ", ".join(_bridge_column(c) for c in columns)
        op.create_check_constraint(name, table, f"num_nonnulls({bridged_list}) = 1")

    for table, name, columns in _PLAIN_INDEXES:
        bridged_cols = [
            _bridge_column(c) if _is_id_column(table, c) else c for c in columns
        ]
        op.create_index(name, table, bridged_cols)


def _rename_columns_into_place() -> None:
    """Steps 15-17: rename the old integer columns out of the way (must
    happen before the uuid columns can take their vacated names), rename
    the uuid columns into the now-canonical names -- every constraint/
    index recreated in _recreate_constraints_and_indexes already follows
    its column by position, not by name, so nothing else needs to change
    here -- then strip the demoted integer columns of both their server
    default and their NOT NULL constraint. Dropping the default alone
    would leave a NOT NULL column no application code writes to any
    more, so every future INSERT would fail outright; a *_legacy_int
    value only ever exists for a row that predates the cutover, so NULL
    is the correct steady state going forward. The sequences themselves
    are intentionally left alive for the Phase-C cleanup migration (a
    later, unhurried, zero-downtime step)."""
    for table in _PK_TABLES:
        op.alter_column(table, "id", new_column_name="id_legacy_int")
    for table, column, _referent, _ondelete, _not_null in _FK_COLUMNS:
        op.alter_column(table, column, new_column_name=_legacy_column(column))

    for table in _PK_TABLES:
        op.alter_column(table, "id_uuid", new_column_name="id")
    for table, column, _referent, _ondelete, _not_null in _FK_COLUMNS:
        op.alter_column(table, _bridge_column(column), new_column_name=column)

    for table in _PK_TABLES:
        op.alter_column(table, "id_legacy_int", nullable=True, server_default=None)
    for table, column, _referent, _ondelete, not_null in _FK_COLUMNS:
        if not_null:
            op.alter_column(table, _legacy_column(column), nullable=True)


def upgrade() -> None:
    """Upgrade schema."""
    _final_backfill()
    _assert_backfill_complete()
    _drop_old_constraints_and_indexes()
    _promote_uuid_primary_keys()
    _recreate_constraints_and_indexes()
    _rename_columns_into_place()


def downgrade() -> None:
    """Deliberately irreversible past this point.

    Every previous DB-hardening migration in this project had a real,
    tested downgrade -- each was additive or type-narrowing over a fixed
    set of rows, so the "before" state was always reconstructible from
    the "after" state. This migration is different: it replaces the
    entire primary-key identity space. The moment a single row is
    inserted after this migration runs, it has a UUIDv7 identity that
    never had an integer counterpart and can never be mapped back to
    one. A downgrade() that "worked" immediately after upgrade() (while
    the *_legacy_int columns are still sitting there unused) would be a
    false promise -- it would only fail, silently or catastrophically,
    at the moment it was actually needed, against real post-cutover
    data. The real rollback path is restoring the pre-cutover backup and
    redeploying the previous release, not an in-place schema reversal.
    """
    msg = (
        "This migration cannot be safely reversed once any row created "
        "after cutover exists -- restore the pre-cutover backup and "
        "redeploy the previous release instead."
    )
    raise RuntimeError(msg)
