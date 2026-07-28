"""Regenerates tests/fixtures/legacy_schema.sql from the real (619 MB)
database/database.sqlite -- a schema-only dump (no rows), small enough to
commit and rebuild an isolated test database from in tests/conftest.py.

Run manually whenever the legacy SQLite schema changes before the Phase 2
Postgres cutover:

    python scripts/dump_test_schema.py
"""

import sqlite3
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SOURCE_DB = _REPO_ROOT / "database" / "database.sqlite"
_TARGET_FIXTURE = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "legacy_schema.sql"
)


def main() -> None:
    conn = sqlite3.connect(_SOURCE_DB)
    try:
        # sqlite_sequence is an internal, auto-created table (backs
        # AUTOINCREMENT columns) -- SQLite reserves its name and refuses an
        # explicit CREATE TABLE for it, even though sqlite_master lists one.
        rows = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name != 'sqlite_sequence' "
            "ORDER BY type DESC, name"
        ).fetchall()
    finally:
        conn.close()

    sql = "\n\n".join(f"{row[0]};" for row in rows)
    _TARGET_FIXTURE.write_text(sql + "\n")
    print(f"Wrote {len(rows)} statements to {_TARGET_FIXTURE}")


if __name__ == "__main__":
    main()
