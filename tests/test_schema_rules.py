"""Catalog-wide checks of the schema rules, run against the schema that the
Alembic migrations produce. They apply to every table, including tables added
later, so a new table that forgets a rule fails here without anyone having to
remember to write a test for it. The rule that every foreign key is indexed
lives in test_foreign_key_indexes.py."""

from typing import TYPE_CHECKING

from sqlalchemy import text

from app.db.database import engine

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import TextClause

_NAIVE_TIMESTAMPS = text(
    """
    SELECT table_name || '.' || column_name
    FROM information_schema.columns
    WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'
    ORDER BY 1
    """
)

_NULLABLE_CREATED_AT = text(
    """
    SELECT table_name
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND column_name = 'created_at'
      AND is_nullable = 'YES'
    ORDER BY 1
    """
)

_TABLES_WITHOUT_UUID_PRIMARY_KEY = text(
    """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND c.relname <> 'alembic_version'
      AND NOT EXISTS (
          SELECT 1
          FROM pg_index i
          JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
          WHERE i.indrelid = c.oid
            AND i.indisprimary
            AND i.indnatts = 1
            AND a.atttypid = 'uuid'::regtype
      )
    ORDER BY 1
    """
)


# The wall-clock times of the church services are kept as naive local time on
# purpose (Settings.app_timezone documents the zone); no other column may be
# a naive timestamp.
_NAIVE_TIMESTAMP_EXCEPTIONS = frozenset(
    {"performance_rehearsals.schedule", "performances.schedule"}
)


def _fetch(statement: TextClause) -> frozenset[str]:
    with engine.connect() as connection:
        return frozenset(connection.execute(statement).scalars().all())


def test_no_new_column_uses_timestamp_without_time_zone():
    assert _fetch(_NAIVE_TIMESTAMPS) - _NAIVE_TIMESTAMP_EXCEPTIONS == frozenset()


def test_the_naive_timestamp_exceptions_are_all_still_in_use():
    assert _NAIVE_TIMESTAMP_EXCEPTIONS - _fetch(_NAIVE_TIMESTAMPS) == frozenset()


def test_no_table_has_a_nullable_created_at():
    assert _fetch(_NULLABLE_CREATED_AT) == frozenset()


def test_every_table_has_a_single_column_uuid_primary_key():
    assert _fetch(_TABLES_WITHOUT_UUID_PRIMARY_KEY) == frozenset()
