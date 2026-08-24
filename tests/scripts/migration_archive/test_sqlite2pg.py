"""Tests for scripts/migration_archive/sqlite2pg.py.

TestMain mirrors tests/scripts/test_backup_db.py's pattern (monkeypatch the
substantial logic, only exercise the CLI glue) -- fast, no real DB needed.

TestMigrate exercises the real copy logic end-to-end and therefore needs a
real, reachable Postgres -- set TEST_MIGRATION_DATABASE_URL to point at one
(a dedicated database, never the app's own dev/prod data: these tests
TRUNCATE every table in whatever database that URL names). Skipped
otherwise rather than failing the whole suite, since this Postgres
dependency predates the Phase 2 CI/conftest cutover (see the migration
plan's M5) that will make one available project-wide.
"""

import os
import sqlite3
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import get_settings
from scripts.migration_archive import sqlite2pg

_FIXTURE_SCHEMA = Path(__file__).parent.parent.parent / "fixtures" / "legacy_schema.sql"
_TEST_DATABASE_URL = os.environ.get("TEST_MIGRATION_DATABASE_URL")

_requires_postgres = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="TEST_MIGRATION_DATABASE_URL not set -- no Postgres to migrate into",
)


@pytest.fixture
def source_sqlite_path(tmp_path: Path) -> Path:
    """A full-schema (all 30 tables), near-empty SQLite file -- same DDL
    conftest.py's own ephemeral test DB is built from, plus a handful of
    hand-seeded rows covering the cases sqlite2pg.py has to get right:
    a boolean column, the one real FK (user_roles), and a NULL id-less row
    (password_reset_tokens)."""
    db_path = tmp_path / "source.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_FIXTURE_SCHEMA.read_text())
        conn.execute(
            'INSERT INTO instruments (id, name, "order", active) '
            "VALUES (1, 'Violine', 0, 1)"
        )
        conn.execute(
            'INSERT INTO roles (id, name, label, "order") '
            "VALUES (1, 'admin', 'Administrator', 0)"
        )
        conn.execute(
            "INSERT INTO users (id, surname, givenname, auth_locked, administrator) "
            "VALUES (1, 'Muster', 'Max', 0, 0)"
        )
        conn.execute("INSERT INTO user_roles (id, user_id, role_id) VALUES (1, 1, 1)")
        conn.execute(
            "INSERT INTO password_reset_tokens (email, token) "
            "VALUES ('test@example.test', 'abc')"
        )
        conn.commit()
    return db_path


@pytest.fixture
def target_database_url(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """Points DATABASE_URL at the dedicated test Postgres and gives it a
    fresh schema via the real `alembic upgrade head` -- not
    Base.metadata.create_all(), which would silently regenerate
    password_reset_tokens' PrimaryKeyConstraint that the actual migration
    (alembic/versions/..._schema_baseline.py) deliberately omits (see the
    M1 fix). Running the real migration here is what makes
    test_password_reset_tokens_has_no_primary_key below a meaningful
    check instead of a tautology."""
    assert (
        _TEST_DATABASE_URL is not None
    )  # narrows the type; module is skipped otherwise
    monkeypatch.setenv("DATABASE_URL", _TEST_DATABASE_URL)
    get_settings.cache_clear()

    engine = create_engine(_TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    command.upgrade(
        Config(str(Path(__file__).parent.parent.parent.parent / "alembic.ini")), "head"
    )

    yield _TEST_DATABASE_URL
    get_settings.cache_clear()


@_requires_postgres
class TestMigrate:
    def test_copies_every_table_and_preserves_row_content(
        self, source_sqlite_path: Path, target_database_url: str
    ):
        counts = sqlite2pg.migrate(str(source_sqlite_path))

        assert counts["instruments"] == 1
        assert counts["users"] == 1
        assert counts["user_roles"] == 1
        assert counts["password_reset_tokens"] == 1
        # Every mapped table is represented, even the ones left empty by
        # the fixture -- confirms Base.metadata.sorted_tables (not a
        # hand-picked subset) drives what gets copied.
        assert len(counts) == 30

    def test_resets_the_target_sequence_past_the_copied_max_id(
        self, source_sqlite_path: Path, target_database_url: str
    ):
        sqlite2pg.migrate(str(source_sqlite_path))

        engine = create_engine(target_database_url)
        with engine.connect() as conn:
            next_id = conn.execute(
                text("SELECT nextval(pg_get_serial_sequence('users', 'id'))")
            ).scalar()
        engine.dispose()

        assert next_id == 2  # one seeded row with id=1 -> sequence continues at 2

    def test_password_reset_tokens_has_no_primary_key(
        self, source_sqlite_path: Path, target_database_url: str
    ):
        """Guards the M1 fix: autogenerate would otherwise have added a
        real PrimaryKeyConstraint on email, which the Legacy table never
        had."""
        sqlite2pg.migrate(str(source_sqlite_path))

        engine = create_engine(target_database_url)
        pk_columns = inspect(engine).get_pk_constraint("password_reset_tokens")[
            "constrained_columns"
        ]
        engine.dispose()

        assert pk_columns == []

    def test_is_idempotent_when_run_twice_in_a_row(
        self, source_sqlite_path: Path, target_database_url: str
    ):
        first = sqlite2pg.migrate(str(source_sqlite_path))
        second = sqlite2pg.migrate(str(source_sqlite_path))

        assert first == second

    def test_tolerates_invalid_utf8_in_the_source_instead_of_crashing(
        self, source_sqlite_path: Path, target_database_url: str
    ):
        # A raw, non-UTF-8 byte sequence, written the same way the
        # legacy data actually contains one (see
        # client_user_agents.string rowid 1283 in the migration plan) --
        # sqlite3 happily stores it, Python's strict-UTF-8 default
        # text_factory refuses to read it back.
        with sqlite3.connect(source_sqlite_path) as conn:
            conn.execute(
                "INSERT INTO client_user_agents (id, string) VALUES (1, ?)",
                (b"bot/1.0 \xa1\xb1",),
            )
            conn.commit()

        counts = sqlite2pg.migrate(str(source_sqlite_path))

        assert counts["client_user_agents"] == 1

    def test_refuses_a_non_postgres_target(
        self, source_sqlite_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{source_sqlite_path}")
        get_settings.cache_clear()

        with pytest.raises(sqlite2pg.MigrationError, match="Postgres"):
            sqlite2pg.migrate(str(source_sqlite_path))

        get_settings.cache_clear()

    def test_raises_for_a_missing_source_file(self, target_database_url: str):
        with pytest.raises(sqlite2pg.MigrationError, match="not found"):
            sqlite2pg.migrate("/nonexistent/database.sqlite")


class TestMain:
    def test_reports_migrated_tables_and_row_counts(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setattr(
            sqlite2pg, "migrate", lambda _source_path: {"users": 3, "roles": 1}
        )
        monkeypatch.setattr(sys, "argv", ["sqlite2pg.py"])

        sqlite2pg.main()

        out = capsys.readouterr().out
        assert "Migrated 2 table(s), 4 row(s) total" in out
        assert "users: 3" in out
        assert "roles: 1" in out

    def test_passes_a_custom_source_path_through(self, monkeypatch: pytest.MonkeyPatch):
        received: dict[str, str] = {}

        def fake_migrate(source_path: str) -> dict[str, int]:
            received["source_path"] = source_path
            return {}

        monkeypatch.setattr(sqlite2pg, "migrate", fake_migrate)
        monkeypatch.setattr(
            sys, "argv", ["sqlite2pg.py", "--source-path", "/data/custom-source.sqlite"]
        )

        sqlite2pg.main()

        assert received["source_path"] == "/data/custom-source.sqlite"

    def test_migration_error_exits_with_code_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def failing_migrate(_source_path: str) -> dict[str, int]:
            msg = "DATABASE_URL must point at Postgres, not sqlite -- refusing to run."
            raise sqlite2pg.MigrationError(msg)

        monkeypatch.setattr(sqlite2pg, "migrate", failing_migrate)
        monkeypatch.setattr(sys, "argv", ["sqlite2pg.py"])

        with pytest.raises(SystemExit) as exc_info:
            sqlite2pg.main()

        assert exc_info.value.code == 1
        assert "must point at Postgres" in capsys.readouterr().err
