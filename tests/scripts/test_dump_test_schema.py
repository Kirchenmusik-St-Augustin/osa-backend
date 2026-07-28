import sqlite3

import pytest

from scripts import dump_test_schema


def test_main_dumps_schema_and_excludes_sqlite_sequence(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    source_db = tmp_path / "source.sqlite"
    target_fixture = tmp_path / "legacy_schema.sql"

    with sqlite3.connect(source_db) as conn:
        # AUTOINCREMENT makes SQLite create the internal sqlite_sequence
        # table -- the exact regression this test guards against.
        conn.execute(
            "CREATE TABLE artists (id integer primary key autoincrement, name varchar)"
        )
        conn.execute("CREATE TABLE fees (id integer primary key, amount integer)")

    monkeypatch.setattr(dump_test_schema, "_SOURCE_DB", source_db)
    monkeypatch.setattr(dump_test_schema, "_TARGET_FIXTURE", target_fixture)

    dump_test_schema.main()

    written = target_fixture.read_text()
    assert "sqlite_sequence" not in written
    assert "CREATE TABLE artists" in written
    assert "CREATE TABLE fees" in written
