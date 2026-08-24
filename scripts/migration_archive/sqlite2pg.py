#!/usr/bin/env python3
"""One-time SQLite -> PostgreSQL data migration for the Phase 2 cutover.

Usage:
    DATABASE_URL=postgresql://... python scripts/migration_archive/sqlite2pg.py \\
        [--source-path PATH]

Options:
    --source-path   Path to the source SQLite file (default:
                     /database/database.sqlite, the container mount path
                     already used throughout this project).

Copies every table's data from the source SQLite file into the Postgres
database reachable via DATABASE_URL (see app.core.config.Settings), using
Base.metadata.sorted_tables as the sole definition of "what to copy" -- 1:1
the tables Alembic's schema baseline (alembic/versions/) already created
there (CLAUDE.md section 3, Phase 2 step 1: a pure structural transfer, no
redesign yet). Integer ids are copied verbatim, no UUID remapping.

migrations/queue_jobs/queue_failed_jobs (dead Laravel tooling tables, no
SQLAlchemy model, never used by this app) are deliberately not copied --
that's a reviewed exclusion, not an oversight.

session_replication_role is deliberately NOT used here (unlike a schema
with many FK constraints): Base.metadata has exactly one real ForeignKey
in the whole schema (user_roles -> users/roles), and
Base.metadata.sorted_tables already topologically orders around it, so
inserting in that order never violates it. TRUNCATE ... CASCADE handles
that one dependency on the way down regardless of order.

Truncate & reload: safe to run more than once against the same target
(e.g. during a dev rehearsal, or a retry after an interrupted production
cutover attempt). Deliberately kept under migration_archive/, not a
permanent operational tool -- delete once the cutover is verified in both
dev and production and Alembic is the sole schema source of truth going
forward.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import Table, create_engine, event, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry

import app.db.base  # noqa: F401 -- registers every model with Base.metadata  # pyright: ignore[reportUnusedImport]
from app.core.config import get_settings
from app.db.database import Base

_DEFAULT_SOURCE_PATH = "/database/database.sqlite"
_BATCH_SIZE = 1000


def _tolerate_invalid_utf8(
    dbapi_connection: DBAPIConnection, _connection_record: ConnectionPoolEntry
) -> None:
    """Replaces sqlite3's default strict-UTF-8 text_factory with a lenient
    one on the source connection only.

    Found during the dev rehearsal: client_user_agents.string (rowid 1283
    in the production copy) holds a bot User-Agent header with a malformed
    byte sequence (b'...help.html\\xa1\\xb1)', likely a GBK fragment mixed
    into an otherwise-UTF-8 value) that SQLite accepted on write but
    Python's default strict decode refuses to even read back. A full scan
    of every TEXT/VARCHAR column in every table found exactly this one
    value -- not a systemic issue. errors="replace" swaps only the invalid
    bytes for U+FFFD, keeping the row (and every other, already-valid
    value) intact rather than losing it entirely.
    """

    def _lenient_decode(raw: bytes) -> str:
        return raw.decode("utf-8", errors="replace")

    dbapi_connection.text_factory = _lenient_decode  # pyright: ignore[reportAttributeAccessIssue] -- sqlite3.Connection-specific attribute, not on the generic DBAPIConnection protocol


class MigrationError(Exception):
    """Raised for a misconfiguration that would make the migration
    meaningless or unsafe to run (wrong target dialect, missing source
    file) -- caught in main() for a clean CLI error instead of a
    traceback."""


def _copy_table(source: Connection, target: Connection, table: Table) -> int:
    """Copies every row of one table from source to target, batched.

    Reading and writing through the same Table object (shared
    Base.metadata) means SQLAlchemy's dialect-aware type coercion runs on
    both ends automatically -- e.g. a Boolean column round-trips as a
    Python bool regardless of SQLite's 0/1 vs. Postgres' native boolean
    on-disk representation, no manual translation needed here.
    """
    rows = [dict(row) for row in source.execute(table.select()).mappings()]
    for offset in range(0, len(rows), _BATCH_SIZE):
        batch = rows[offset : offset + _BATCH_SIZE]
        if batch:
            target.execute(table.insert(), batch)
    return len(rows)


def _reset_sequence(target: Connection, table: Table) -> None:
    """Advances the target's identity sequence past the highest copied id.

    Bulk-inserting explicit id values never advances the sequence itself,
    so without this the next id the running app assigns post-cutover would
    collide with one that arrived through this copy.
    """
    if "id" not in table.c:
        return  # e.g. password_reset_tokens, which has no id column at all
    max_id = target.execute(select(func.max(table.c.id))).scalar()
    if max_id is None:
        return  # empty table, sequence already starts at its default
    target.execute(
        text("SELECT setval(pg_get_serial_sequence(:table, 'id'), :max_id)"),
        {"table": table.name, "max_id": max_id},
    )


def _truncate_all(target: Connection, tables: Sequence[Table]) -> None:
    quote = target.dialect.identifier_preparer.quote
    quoted_names = ", ".join(quote(table.name) for table in tables)
    target.execute(text(f"TRUNCATE TABLE {quoted_names} RESTART IDENTITY CASCADE"))


def migrate(source_path: str) -> dict[str, int]:
    """Runs the full copy, returns {table_name: row_count} for the CLI to
    report and for tests to assert against."""
    if not Path(source_path).is_file():
        msg = f"Source SQLite file not found: {source_path}"
        raise MigrationError(msg)

    target_url = cast("str", get_settings().database_url)
    target_engine = create_engine(target_url)
    if target_engine.dialect.name != "postgresql":
        target_engine.dispose()
        msg = (
            f"DATABASE_URL must point at Postgres, not "
            f"{target_engine.dialect.name} -- refusing to run."
        )
        raise MigrationError(msg)

    source_engine = create_engine(f"sqlite:///{source_path}")
    event.listens_for(source_engine, "connect")(_tolerate_invalid_utf8)
    tables = Base.metadata.sorted_tables
    counts: dict[str, int] = {}

    try:
        with source_engine.connect() as source, target_engine.begin() as target:
            _truncate_all(target, tables)
            for table in tables:
                counts[table.name] = _copy_table(source, target, table)
                _reset_sequence(target, table)
    finally:
        source_engine.dispose()
        target_engine.dispose()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time SQLite -> Postgres data migration (Phase 2 cutover).",
    )
    parser.add_argument(
        "--source-path",
        default=_DEFAULT_SOURCE_PATH,
        help=f"Path to the source SQLite file (default: {_DEFAULT_SOURCE_PATH}).",
    )
    args = parser.parse_args()

    try:
        counts = migrate(args.source_path)
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    total = sum(counts.values())
    print(f"Migrated {len(counts)} table(s), {total} row(s) total:")
    for name, count in counts.items():
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
