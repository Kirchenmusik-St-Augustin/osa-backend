import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CalledProcessError
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import requests

from app.services import backup_service
from app.services.backup_service import BackupError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from typing import BinaryIO

PG_URL = "postgresql://user:secret@localhost:5432/testdb"
NON_POSTGRES_URL = "mysql://user:secret@localhost:3306/testdb"
FAKE_PG_DUMP = "/usr/bin/pg_dump"
FAKE_PG_RESTORE = "/usr/bin/pg_restore"
FAKE_PSQL = "/usr/bin/psql"
_FAKE_PG_TOOLS = {
    "pg_dump": FAKE_PG_DUMP,
    "pg_restore": FAKE_PG_RESTORE,
    "psql": FAKE_PSQL,
}


def _which_side_effect(name: str) -> str:
    return _FAKE_PG_TOOLS[name]


def _fake_pg_subprocess_run(
    calls: list[list[str]], *, row_count: bytes = b"5"
) -> Callable[..., MagicMock]:
    """Build a subprocess.run fake that records every call and answers
    _verify_restore_populated()'s row-count query with `row_count` --
    every other psql/pg_restore invocation gets a generic empty stdout,
    matching what the real tools' non-SELECT statements return."""

    def fake_run(args: list[str], **_kw: object) -> MagicMock:
        calls.append(args)
        if "SUM(n_live_tup)" in args[-1]:
            return MagicMock(stdout=row_count, returncode=0)
        return MagicMock(stdout=b"", returncode=0)

    return fake_run


def _fake_pg_dump_writing(dump: bytes) -> Callable[..., MagicMock]:
    """subprocess.run fake for run_backup(): like the real pg_dump it writes
    the dump to the file named by --file and leaves stdout empty."""

    def fake_run(args: list[str], **_kw: object) -> MagicMock:
        target = next(arg for arg in args if arg.startswith("--file="))
        Path(target.removeprefix("--file=")).write_bytes(dump)
        return MagicMock(stdout=b"", returncode=0)

    return fake_run


class _FakeResponse:
    def __init__(
        self, *, status_code: int = 200, content: bytes = b"", text: str = ""
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.text = text

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            msg = f"status {self.status_code}"
            raise requests.HTTPError(msg)

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start : start + chunk_size]


class _FakeEngine:
    """Stand-in for app.db.database's SQLAlchemy engine, used to verify
    run_restore()'s post-restore dispose() call without touching the real
    connection pool other tests/fixtures rely on."""

    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class TestParseDbUrl:
    def test_simple_url(self):
        host, user, password, port, dbname = backup_service._parse_db_url(PG_URL)
        assert (host, user, password, port, dbname) == (
            "localhost",
            "user",
            "secret",
            5432,
            "testdb",
        )

    def test_default_port_when_missing(self):
        _, _, _, port, _ = backup_service._parse_db_url(
            "postgresql://user:secret@localhost/testdb"
        )
        assert port == 5432

    def test_password_containing_slash(self):
        """Regression test: urllib.parse.urlparse treats the first '/'
        after '://' as the start of the path, so a password containing '/'
        (common in randomly-generated passwords, e.g. base64-derived) makes
        it misparse the whole netloc and raise `ValueError: Port could not
        be cast to integer value`. make_url() (the same parser
        create_engine() already uses successfully for this DATABASE_URL
        elsewhere in the app) handles it correctly."""
        host, user, password, port, dbname = backup_service._parse_db_url(
            "postgresql://osa:has/slash@localhost:5432/osa"
        )
        assert (host, user, password, port, dbname) == (
            "localhost",
            "osa",
            "has/slash",
            5432,
            "osa",
        )


class TestPgEnvironment:
    def test_carries_only_what_libpq_needs(self):
        assert backup_service._build_pg_env("s3cret") == {
            "PGPASSWORD": "s3cret",
            "PGCONNECT_TIMEOUT": "10",
        }

    def test_every_pg_subprocess_runs_without_the_application_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        environments: list[dict[str, str]] = []

        def fake_run(_args: list[str], **kwargs: dict[str, str]) -> MagicMock:
            environments.append(kwargs["env"])
            return MagicMock(stdout=b"5", returncode=0)

        monkeypatch.setattr(backup_service.subprocess, "run", fake_run)
        monkeypatch.setattr(
            backup_service.requests, "put", lambda *_a, **_kw: _FakeResponse()
        )
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(content=b"dump"),
        )
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())

        backup_service.run_backup()
        backup_service.run_restore(
            backup_name="production-2026-01-01_00-00-00.dump", force=True
        )

        assert len(environments) >= 6
        assert all(
            set(env) == {"PGPASSWORD", "PGCONNECT_TIMEOUT"} for env in environments
        )


class TestRequirePostgres:
    def test_names_the_scheme_but_never_the_credentials(self):
        with pytest.raises(BackupError) as exc_info:
            backup_service._require_postgres(NON_POSTGRES_URL)

        message = str(exc_info.value)
        assert "mysql" in message
        assert "secret" not in message
        assert "user" not in message
        assert "localhost" not in message

    def test_a_value_without_a_scheme_is_not_echoed(self):
        with pytest.raises(BackupError) as exc_info:
            backup_service._require_postgres("user:secret@localhost/testdb")

        assert "secret" not in str(exc_info.value)

    def test_accepts_a_postgres_url(self):
        backup_service._require_postgres(PG_URL)


class TestRunBackup:
    @pytest.fixture(autouse=True)
    def _production_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # run_backup() is production-only (see its docstring) -- every test
        # in this class exercises the success/failure paths past that gate,
        # so production is this class's ambient default. The one test that
        # targets the gate itself overrides this back down.
        monkeypatch.setenv("APP_ENVIRONMENT", "production")

    def test_uploads_a_dump_with_stage_prefixed_name(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.subprocess, "run", _fake_pg_dump_writing(b"PG_DUMP_DATA")
        )

        uploaded: dict[str, object] = {}

        def fake_put(
            url: str, *, data: BinaryIO, auth: object, **_kwargs: object
        ) -> _FakeResponse:
            uploaded["url"] = url
            uploaded["data"] = data.read()
            uploaded["auth"] = auth
            return _FakeResponse(status_code=200)

        monkeypatch.setattr(backup_service.requests, "put", fake_put)

        archive_name = backup_service.run_backup()

        match = backup_service._FILENAME_PATTERN.match(archive_name)
        assert match is not None
        # APP_ENVIRONMENT is "production" here (see _production_env above --
        # run_backup() only ever succeeds in that stage).
        assert match.group("stage") == "production"
        assert not archive_name.endswith("-manual.dump")
        assert str(uploaded["url"]).endswith(archive_name)
        assert uploaded["auth"] == ("user", "pw")
        assert uploaded["data"] == b"PG_DUMP_DATA"

    def test_excludes_job_runs_row_data_from_the_dump(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """job_runs holds this stage's own scheduled-job run history -- a
        shared backup must never carry it, or a downsync/restore on another
        stage would silently replace that stage's own history with this
        one's (see run_restore()'s preserve mechanism, which relies on this
        exclusion to have already happened)."""
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "put",
            lambda *_a, **_kw: _FakeResponse(status_code=200),
        )

        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kw: object) -> MagicMock:
            calls.append(args)
            return MagicMock(stdout=b"x", returncode=0)

        monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

        backup_service.run_backup()

        assert len(calls) == 1
        assert "--exclude-table-data=public.job_runs" in calls[0]

    def test_manual_true_tags_the_filename_with_a_manual_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.subprocess,
            "run",
            lambda *_a, **_kw: MagicMock(stdout=b"x", returncode=0),
        )
        monkeypatch.setattr(
            backup_service.requests,
            "put",
            lambda *_a, **_kw: _FakeResponse(status_code=200),
        )

        archive_name = backup_service.run_backup(manual=True)

        assert archive_name.endswith("-manual.dump")
        assert backup_service._FILENAME_PATTERN.match(archive_name)

    def test_raises_for_a_non_postgres_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", NON_POSTGRES_URL)

        with pytest.raises(BackupError, match="PostgreSQL"):
            backup_service.run_backup()

    def test_raises_when_pg_dump_is_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setattr(backup_service.shutil, "which", lambda _name: None)

        with pytest.raises(BackupError, match="pg_dump"):
            backup_service.run_backup()

    def test_raises_when_pg_dump_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)

        def fake_run(*_a: object, **_kw: object) -> None:
            raise CalledProcessError(
                1, "pg_dump", stderr=b"FATAL: password authentication failed"
            )

        monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

        with pytest.raises(BackupError, match="password authentication failed"):
            backup_service.run_backup()

    def test_raises_when_koofr_upload_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.subprocess,
            "run",
            lambda *_a, **_kw: MagicMock(stdout=b"x", returncode=0),
        )

        def fake_put(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "boom"
            raise requests.ConnectionError(msg)

        monkeypatch.setattr(backup_service.requests, "put", fake_put)

        with pytest.raises(BackupError, match="upload failed"):
            backup_service.run_backup()

    def test_raises_when_koofr_credentials_are_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.delenv("KOOFR_USER", raising=False)
        monkeypatch.delenv("KOOFR_PASSWORD", raising=False)
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.subprocess,
            "run",
            lambda *_a, **_kw: MagicMock(stdout=b"x", returncode=0),
        )

        with pytest.raises(BackupError, match="KOOFR_USER"):
            backup_service.run_backup()

    def test_uses_the_configured_app_timezone_not_utc_for_the_filename_timestamp(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression guard: run_backup()'s filename stamp
        must match the Vienna wall-clock the backup_koofr scheduler trigger
        fires in (Settings.backup_hour/minute, app_timezone), not UTC -- a
        UTC-stamped filename would disagree with the scheduler's own
        timezone by the current UTC offset."""
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.subprocess,
            "run",
            lambda *_a, **_kw: MagicMock(stdout=b"x", returncode=0),
        )
        monkeypatch.setattr(
            backup_service.requests,
            "put",
            lambda *_a, **_kw: _FakeResponse(status_code=200),
        )
        fixed_local = datetime(2026, 8, 14, 3, 0, 0)  # noqa: DTZ001 -- naive Vienna wall-clock, matches local_now()'s own convention
        monkeypatch.setattr(backup_service, "local_now", lambda: fixed_local)

        archive_name = backup_service.run_backup()

        assert "2026-08-14_03-00-00" in archive_name

    def test_refuses_outside_production(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("APP_ENVIRONMENT", "test")

        def unexpected_run(*_a: object, **_kw: object) -> None:
            msg = "pg_dump must not run when backup is blocked by the environment gate"
            raise AssertionError(msg)

        monkeypatch.setattr(backup_service.subprocess, "run", unexpected_run)

        with pytest.raises(BackupError, match="production"):
            backup_service.run_backup()


# Deliberately absolute WebDAV hrefs (not bare filenames) -- see
# TestListBackups' regression test below.
_PROPFIND_XML = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2024-01-02_10-00-00.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Tue, 02 Jan 2024 10:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2024-01-01_09-00-00.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Mon, 01 Jan 2024 09:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/not-a-backup.txt</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Mon, 01 Jan 2024 09:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>
"""


class TestListBackups:
    def test_extracts_basenames_even_from_absolute_webdav_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression test for the double-prefixing pitfall this module
        deliberately avoids (see backup_service's module docstring): Koofr's
        PROPFIND response returns absolute WebDAV hrefs, not bare
        filenames -- list_backups() must still resolve to correct
        basenames, and cleanup_old_backups()/run_restore() must be able to
        act on them without any double-prefixing."""
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        def fake_request(
            method: str, *_args: object, **_kwargs: object
        ) -> _FakeResponse:
            assert method == "PROPFIND"
            return _FakeResponse(status_code=200, text=_PROPFIND_XML)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        names = backup_service.list_backups()

        assert names == [
            "production-2024-01-01_09-00-00.dump",
            "production-2024-01-02_10-00-00.dump",
        ]

    def test_sorts_chronologically_across_differently_staged_backups(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression test for the stage-prefix naming change (2026-08-13):
        a plain string sort would order by stage name first, putting every
        "development-..." name before every "production-..." one
        regardless of actual age (since "d" < "p"). list_backups() must
        sort by the parsed timestamp instead, so the true chronological
        order survives even when it disagrees with alphabetical order."""
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        propfind_xml = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/development-2024-06-01_00-00-00.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Sat, 01 Jun 2024 00:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2024-01-01_00-00-00.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>
"""

        def fake_request(*_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse(status_code=200, text=propfind_xml)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        names = backup_service.list_backups()

        # Oldest-first: the January "production" backup precedes the June
        # "development" one, even though "development" < "production"
        # alphabetically.
        assert names == [
            "production-2024-01-01_00-00-00.dump",
            "development-2024-06-01_00-00-00.dump",
        ]

    def test_skips_a_self_closing_href_with_no_text(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        # A self-closing <d:href/> (no text content at all) is a defensive
        # edge case some WebDAV servers can produce for odd entries --
        # must be skipped, not crash on `.rstrip()` against None.
        propfind_xml = (
            '<?xml version="1.0"?>'
            '<d:multistatus xmlns:d="DAV:">'
            "<d:response><d:href/></d:response>"
            "</d:multistatus>"
        )
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        def fake_request(*_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse(status_code=200, text=propfind_xml)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        assert backup_service.list_backups() == []

    def test_stage_filter_keeps_only_matching_backups(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression guard for the downsync feature (2026-08-21): a
        manually-triggered backup is callable from any stage and lands in
        this same shared Koofr path, so list_backups(stage="production")
        must exclude non-production entries rather than silently picking
        one up as "the latest production backup"."""
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        propfind_xml = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/test-2024-06-01_00-00-00-manual.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Sat, 01 Jun 2024 00:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2024-01-01_00-00-00.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Mon, 01 Jan 2024 00:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>
"""

        def fake_request(*_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse(status_code=200, text=propfind_xml)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        names = backup_service.list_backups(stage="production")

        assert names == ["production-2024-01-01_00-00-00.dump"]

    def test_stage_filter_returns_empty_list_when_no_match(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        def fake_request(*_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse(status_code=200, text=_PROPFIND_XML)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        assert backup_service.list_backups(stage="qa") == []

    def test_raises_when_propfind_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.time, "sleep", lambda _seconds: None)

        attempts = 0

        def fake_request(*_args: object, **_kwargs: object) -> _FakeResponse:
            nonlocal attempts
            attempts += 1
            msg = "timed out"
            raise requests.Timeout(msg)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        with pytest.raises(BackupError, match="listing failed"):
            backup_service.list_backups()

        # Proves the retry wrapper is actually wired in here, not a dead
        # helper that only exists in isolation.
        assert attempts == 3

    def test_sorts_correctly_across_pre_and_post_fix_names_despite_the_bounded_skew(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """An old UTC-tagged name (pre-2026-08-14 timestamp-source fix) and
        a new Vienna-tagged name from a different day must still sort
        correctly -- the <=2h semantic skew the fix introduces between old
        and new filenames never approaches a full day apart, so cross-day
        ordering is unaffected and no backfill/rename of already-uploaded
        names is needed."""
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        propfind_xml = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2026-08-13_20-50-14-manual.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Thu, 13 Aug 2026 20:50:14 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2026-08-14_03-00-00.dump</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Fri, 14 Aug 2026 03:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>
"""

        def fake_request(*_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse(status_code=200, text=propfind_xml)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        names = backup_service.list_backups()

        assert names == [
            "production-2026-08-13_20-50-14-manual.dump",
            "production-2026-08-14_03-00-00.dump",
        ]


class TestPropfindParsing:
    _BILLION_LAUGHS = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        '<d:multistatus xmlns:d="DAV:"><d:response><d:href>&lol2;</d:href>'
        "</d:response></d:multistatus>"
    )

    def test_refuses_a_listing_that_carries_a_dtd(self):
        with pytest.raises(BackupError, match="DTD"):
            backup_service._parse_backup_filenames(self._BILLION_LAUGHS)

    def test_refuses_a_bare_entity_declaration(self):
        with pytest.raises(BackupError, match="DTD"):
            backup_service._parse_backup_filenames(
                '<!ENTITY a "b"><d:multistatus xmlns:d="DAV:"/>'
            )

    def test_still_parses_comments_and_cdata(self):
        listing = (
            '<?xml version="1.0"?><!-- listing -->'
            '<d:multistatus xmlns:d="DAV:"><d:response><d:href>'
            "<![CDATA[/dav/Backups/production-2026-01-01_00-00-00.dump]]>"
            "</d:href></d:response></d:multistatus>"
        )

        assert backup_service._parse_backup_filenames(listing) == [
            "production-2026-01-01_00-00-00.dump"
        ]


class TestCleanupOldBackups:
    def test_deletes_only_entries_past_retention(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setenv("KOOFR_BACKUP_RETENTION_DAYS", "28")

        now = datetime.now(UTC)
        old_stamp = f"{(now - timedelta(days=30)):%Y-%m-%d_%H-%M-%S}"
        fresh_stamp = f"{(now - timedelta(days=1)):%Y-%m-%d_%H-%M-%S}"
        old_name = f"production-{old_stamp}.dump"
        fresh_name = f"production-{fresh_stamp}.dump"
        monkeypatch.setattr(
            backup_service, "list_backups", lambda: [old_name, fresh_name]
        )

        deleted_urls: list[str] = []

        def fake_delete(url: str, **_kwargs: object) -> _FakeResponse:
            deleted_urls.append(url)
            return _FakeResponse(status_code=200)

        monkeypatch.setattr(backup_service.requests, "delete", fake_delete)

        affected = backup_service.cleanup_old_backups()

        assert affected == [old_name]
        assert len(deleted_urls) == 1
        assert deleted_urls[0].endswith(old_name)

    def test_raises_when_koofr_delete_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.time, "sleep", lambda _seconds: None)

        old_name = "production-2000-01-01_00-00-00.dump"
        monkeypatch.setattr(backup_service, "list_backups", lambda: [old_name])

        def fake_delete(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "server error"
            raise requests.ConnectionError(msg)

        monkeypatch.setattr(backup_service.requests, "delete", fake_delete)

        with pytest.raises(BackupError, match="delete failed"):
            backup_service.cleanup_old_backups()

    def test_dry_run_reports_without_deleting(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        old_name = "production-2000-01-01_00-00-00.dump"
        monkeypatch.setattr(backup_service, "list_backups", lambda: [old_name])

        def fail_delete(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "dry_run must never call requests.delete"
            raise AssertionError(msg)

        monkeypatch.setattr(backup_service.requests, "delete", fail_delete)

        affected = backup_service.cleanup_old_backups(dry_run=True)

        assert affected == [old_name]

    def test_uses_local_now_not_utc_for_the_retention_cutoff(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression: the deletion boundary must be computed from the same
        Vienna wall-clock (local_now()) the filenames themselves are now
        stamped in, not datetime.now(UTC) -- otherwise the cutoff would
        silently drift from what the filenames actually encode by the
        current UTC offset."""
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setenv("KOOFR_BACKUP_RETENTION_DAYS", "28")
        fixed_local = datetime(2026, 8, 14, 3, 0, 0)  # noqa: DTZ001 -- naive Vienna wall-clock
        monkeypatch.setattr(backup_service, "local_now", lambda: fixed_local)

        # Exactly straddling the 28-day cutoff computed from the mocked
        # local_now() above (2026-08-14 03:00:00 - 28d = 2026-07-17
        # 03:00:00) -- proves cleanup_old_backups() actually anchors on
        # local_now(), not some other clock.
        kept_name = "production-2026-07-17_03-00-01.dump"
        deleted_name = "production-2026-07-17_02-59-59.dump"
        monkeypatch.setattr(
            backup_service, "list_backups", lambda: [deleted_name, kept_name]
        )

        deleted_urls: list[str] = []

        def fake_delete(url: str, **_kwargs: object) -> _FakeResponse:
            deleted_urls.append(url)
            return _FakeResponse(status_code=200)

        monkeypatch.setattr(backup_service.requests, "delete", fake_delete)

        affected = backup_service.cleanup_old_backups()

        assert affected == [deleted_name]
        assert deleted_urls[0].endswith(deleted_name)

    def test_never_touches_a_non_matching_name(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        names = ["not-a-backup.txt"]
        monkeypatch.setattr(backup_service, "list_backups", lambda: names)

        def fail_delete(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "a non-matching name must never be deleted"
            raise AssertionError(msg)

        monkeypatch.setattr(backup_service.requests, "delete", fail_delete)

        assert backup_service.cleanup_old_backups() == []


class TestRunRestore:
    def test_refuses_in_production_without_force(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("APP_ENVIRONMENT", "production")

        with pytest.raises(BackupError, match="force"):
            backup_service.run_restore()

    def test_raises_for_a_non_postgres_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", NON_POSTGRES_URL)

        with pytest.raises(BackupError, match="PostgreSQL"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump"
            )

    def test_raises_when_koofr_download_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.time, "sleep", lambda _seconds: None)

        def fake_get(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "connection reset"
            raise requests.ConnectionError(msg)

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        with pytest.raises(BackupError, match="download failed"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump",
                force=True,
            )

    def test_wipes_schema_then_restores_the_downloaded_dump(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(status_code=200, content=b"DUMP_BYTES"),
        )
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())

        calls: list[list[str]] = []
        monkeypatch.setattr(
            backup_service.subprocess, "run", _fake_pg_subprocess_run(calls)
        )

        backup_name = "production-2024-01-01_00-00-00.dump"
        result = backup_service.run_restore(backup_name=backup_name, force=True)

        assert result == backup_name
        # pg_dump (preserve job_runs), psql (wipe), pg_restore (main),
        # psql (ANALYZE), psql (row-count verify), pg_restore (reinsert
        # preserved job_runs) -- see run_restore()'s own ordering comment
        # for why the reinsert happens AFTER the row-count verification.
        assert len(calls) == 6
        assert calls[0][0] == FAKE_PG_DUMP
        assert "--data-only" in calls[0]
        assert "--table=public.job_runs" in calls[0]
        assert calls[1][0] == FAKE_PSQL
        # Terminates every other session (only its own excluded), then wipes.
        assert "pg_terminate_backend(pid)" in calls[1][-1]
        assert "pid != pg_backend_pid()" in calls[1][-1]
        assert "DROP SCHEMA public CASCADE" in calls[1][-1]
        assert calls[2][0] == FAKE_PG_RESTORE
        assert "--data-only" not in calls[2]
        assert calls[3][0] == FAKE_PSQL
        assert calls[3][-1] == "ANALYZE;"
        assert calls[4][0] == FAKE_PSQL
        assert "SUM(n_live_tup)" in calls[4][-1]
        assert calls[5][0] == FAKE_PG_RESTORE
        assert "--data-only" in calls[5]

    def test_main_restore_ignores_ownership_and_privileges_of_the_dump(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """A role without superuser rights cannot reassign objects, so the
        main restore must not replay the dump's OWNER TO and GRANT
        statements; the data-only reinsert of job_runs has none to skip."""
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(status_code=200, content=b"DUMP_BYTES"),
        )
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())

        calls: list[list[str]] = []
        monkeypatch.setattr(
            backup_service.subprocess, "run", _fake_pg_subprocess_run(calls)
        )

        backup_service.run_restore(
            backup_name="production-2024-01-01_00-00-00.dump", force=True
        )

        main_restore = [
            call
            for call in calls
            if call[0] == FAKE_PG_RESTORE and "--data-only" not in call
        ]
        assert len(main_restore) == 1
        assert "--no-owner" in main_restore[0]
        assert "--no-acl" in main_restore[0]

    def test_raises_when_the_restored_database_ends_up_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression guard: a pg_restore that exits 0 does not guarantee
        any rows actually landed -- pg_restore's own error-tolerant default
        can skip a failed statement without a non-zero exit, so an
        automated restore can silently report success while leaving every
        table empty."""
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(status_code=200, content=b"x"),
        )
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())
        monkeypatch.setattr(
            backup_service.subprocess,
            "run",
            _fake_pg_subprocess_run([], row_count=b"0"),
        )

        with pytest.raises(BackupError, match="zero rows"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump", force=True
            )

    def test_raises_when_pg_restore_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(status_code=200, content=b"x"),
        )

        call_count = 0

        def fake_run(args: list[str], **_kw: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if args[0] == FAKE_PG_RESTORE:
                raise CalledProcessError(1, "pg_restore", stderr=b"unexpected EOF")
            return MagicMock(stdout=b"", returncode=0)

        monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

        with pytest.raises(BackupError, match="unexpected EOF"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump", force=True
            )

    def test_auto_selects_the_latest_backup(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.subprocess, "run", _fake_pg_subprocess_run([])
        )
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())

        older = "production-2024-01-01_00-00-00.dump"
        newest = "production-2024-06-01_00-00-00.dump"
        received_stage: dict[str, str | None] = {}

        def fake_list_backups(*, stage: str | None = None) -> list[str]:
            received_stage["stage"] = stage
            return [older, newest]

        monkeypatch.setattr(backup_service, "list_backups", fake_list_backups)

        requested_urls: list[str] = []

        def fake_get(url: str, **_kwargs: object) -> _FakeResponse:
            requested_urls.append(url)
            return _FakeResponse(status_code=200, content=b"x")

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        result = backup_service.run_restore(force=True)

        assert result == newest
        assert requested_urls[0].endswith(newest)
        # Regression guard: auto-select must only ever consider production
        # backups, never an older non-production dump that happens to sort
        # after it.
        assert received_stage["stage"] == "production"

    def test_rejects_a_malformed_backup_name_before_any_network_call(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)

        def fail_get(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "no network call for an invalid backup name"
            raise AssertionError(msg)

        monkeypatch.setattr(backup_service.requests, "get", fail_get)

        with pytest.raises(BackupError, match="not a valid backup filename"):
            backup_service.run_restore(backup_name="../../etc/passwd")

    def test_raises_when_no_backups_exist_for_auto_select(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service, "list_backups", lambda **_kwargs: [])

        with pytest.raises(BackupError, match="No production backups found"):
            backup_service.run_restore(force=True)

    def test_disposes_the_engine_after_a_successful_restore(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Regression guard: _wipe_public_schema() terminates every other
        session on this database (including any this app's own connection
        pool was holding idle) -- the pool must be disposed afterward so
        the next request opens a fresh connection instead of reusing one
        the wipe just killed server-side."""
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(status_code=200, content=b"x"),
        )
        monkeypatch.setattr(
            backup_service.subprocess, "run", _fake_pg_subprocess_run([])
        )

        fake_engine = _FakeEngine()
        monkeypatch.setattr(backup_service, "engine", fake_engine)

        backup_service.run_restore(
            backup_name="production-2024-01-01_00-00-00.dump", force=True
        )

        assert fake_engine.disposed is True

    def test_does_not_dispose_the_engine_when_the_download_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        def fake_get(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "connection reset"
            raise requests.ConnectionError(msg)

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        fake_engine = _FakeEngine()
        monkeypatch.setattr(backup_service, "engine", fake_engine)

        with pytest.raises(BackupError):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump", force=True
            )

        assert fake_engine.disposed is False

    def test_restore_still_succeeds_when_preserving_job_runs_fails(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """The pre-wipe job_runs preserve step (see
        backup_service._preserve_job_runs_before_wipe()) is best-effort --
        a failure there (e.g. this stage's very first restore ever, before
        job_runs exists) must never abort the restore itself."""
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(status_code=200, content=b"x"),
        )
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())

        def fake_run(args: list[str], **_kw: object) -> MagicMock:
            if args[0] == FAKE_PG_DUMP:
                raise CalledProcessError(
                    1, "pg_dump", stderr=b'relation "job_runs" does not exist'
                )
            if "SUM(n_live_tup)" in args[-1]:
                return MagicMock(stdout=b"5", returncode=0)
            return MagicMock(stdout=b"", returncode=0)

        monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

        with caplog.at_level(logging.ERROR):
            result = backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump", force=True
            )

        assert result == "production-2024-01-01_00-00-00.dump"
        assert "could not preserve" in caplog.text.lower()

    def test_restore_still_succeeds_when_reinserting_job_runs_fails(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """The post-restore job_runs reinsert step (see
        backup_service._restore_preserved_job_runs()) is best-effort too --
        by the time it runs, the actual restore has already succeeded and
        passed _verify_restore_populated()."""
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(status_code=200, content=b"x"),
        )
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())

        restore_calls: list[list[str]] = []

        def fake_run(args: list[str], **_kw: object) -> MagicMock:
            if args[0] == FAKE_PG_RESTORE:
                restore_calls.append(args)
                if "--data-only" in args:
                    raise CalledProcessError(1, "pg_restore", stderr=b"broken pipe")
                return MagicMock(stdout=b"", returncode=0)
            if "SUM(n_live_tup)" in args[-1]:
                return MagicMock(stdout=b"5", returncode=0)
            return MagicMock(stdout=b"", returncode=0)

        monkeypatch.setattr(backup_service.subprocess, "run", fake_run)

        with caplog.at_level(logging.ERROR):
            result = backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump", force=True
            )

        assert result == "production-2024-01-01_00-00-00.dump"
        assert len(restore_calls) == 2
        assert "could not reinsert" in caplog.text.lower()


class _InterruptedResponse(_FakeResponse):
    """A download whose connection breaks after the first block."""

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        yield b"PARTIAL"
        msg = "connection broken"
        raise requests.exceptions.ChunkedEncodingError(msg)


class TestStreamedTransfers:
    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(backup_service, "engine", _FakeEngine())
        monkeypatch.setattr(backup_service.time, "sleep", lambda _seconds: None)
        # Every temporary file of the code under test lands in tmp_path, so a
        # test can assert that nothing is left behind.
        monkeypatch.setattr(backup_service.tempfile, "tempdir", str(tmp_path))

    def test_dump_goes_to_a_file_and_is_uploaded_as_a_stream(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        arguments: list[list[str]] = []
        fake_dump = _fake_pg_dump_writing(b"PG_DUMP_DATA")

        def recording_run(args: list[str], **kwargs: object) -> MagicMock:
            arguments.append(args)
            return fake_dump(args, **kwargs)

        sent: dict[str, object] = {}

        def fake_put(_url: str, *, data: BinaryIO, **_kw: object) -> _FakeResponse:
            sent["is_stream"] = hasattr(data, "read") and not isinstance(data, bytes)
            sent["content"] = data.read()
            return _FakeResponse()

        monkeypatch.setattr(backup_service.subprocess, "run", recording_run)
        monkeypatch.setattr(backup_service.requests, "put", fake_put)

        backup_service.run_backup()

        assert any(arg.startswith("--file=") for arg in arguments[0])
        assert sent == {"is_stream": True, "content": b"PG_DUMP_DATA"}
        assert list(tmp_path.iterdir()) == []

    def test_dump_file_is_removed_when_pg_dump_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        def failing_run(args: list[str], **_kw: object) -> MagicMock:
            target = next(arg for arg in args if arg.startswith("--file="))
            Path(target.removeprefix("--file=")).write_bytes(b"half a dump")
            raise CalledProcessError(1, "pg_dump", stderr=b"boom")

        monkeypatch.setattr(backup_service.subprocess, "run", failing_run)

        with pytest.raises(BackupError, match="pg_dump failed"):
            backup_service.run_backup()

        assert list(tmp_path.iterdir()) == []

    def test_dump_file_is_removed_when_the_upload_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        def failing_put(*_a: object, **_kw: object) -> _FakeResponse:
            msg = "boom"
            raise requests.ConnectionError(msg)

        monkeypatch.setattr(
            backup_service.subprocess, "run", _fake_pg_dump_writing(b"dump")
        )
        monkeypatch.setattr(backup_service.requests, "put", failing_put)

        with pytest.raises(BackupError, match="upload failed"):
            backup_service.run_backup()

        assert list(tmp_path.iterdir()) == []

    def test_restore_reads_the_dump_from_a_file_that_was_downloaded_in_blocks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(backup_service, "_TRANSFER_CHUNK_BYTES", 4)
        requested: dict[str, object] = {}

        def fake_get(_url: str, **kwargs: object) -> _FakeResponse:
            requested.update(kwargs)
            return _FakeResponse(content=b"0123456789")

        restored: list[bytes] = []
        base_run = _fake_pg_subprocess_run([])

        def recording_run(args: list[str], **kwargs: object) -> MagicMock:
            if args[0] == FAKE_PG_RESTORE and "--no-owner" in args:
                restored.append(Path(args[-1]).read_bytes())
            return base_run(args, **kwargs)

        monkeypatch.setattr(backup_service.requests, "get", fake_get)
        monkeypatch.setattr(backup_service.subprocess, "run", recording_run)

        backup_service.run_restore(
            backup_name="production-2024-01-01_00-00-00.dump", force=True
        )

        assert requested["stream"] is True
        assert restored == [b"0123456789"]
        assert list(tmp_path.iterdir()) == []

    def test_a_partial_download_is_discarded_before_the_retry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        responses = iter([_InterruptedResponse(), _FakeResponse(content=b"COMPLETE")])
        restored: list[bytes] = []
        base_run = _fake_pg_subprocess_run([])

        def recording_run(args: list[str], **kwargs: object) -> MagicMock:
            if args[0] == FAKE_PG_RESTORE and "--no-owner" in args:
                restored.append(Path(args[-1]).read_bytes())
            return base_run(args, **kwargs)

        monkeypatch.setattr(
            backup_service.requests, "get", lambda *_a, **_kw: next(responses)
        )
        monkeypatch.setattr(backup_service.subprocess, "run", recording_run)

        backup_service.run_restore(
            backup_name="production-2024-01-01_00-00-00.dump", force=True
        )

        assert restored == [b"COMPLETE"]
        assert list(tmp_path.iterdir()) == []

    def test_no_file_is_left_when_every_download_attempt_breaks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            backup_service.requests, "get", lambda *_a, **_kw: _InterruptedResponse()
        )

        with pytest.raises(BackupError, match="download failed"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump", force=True
            )

        assert list(tmp_path.iterdir()) == []

    def test_dump_file_is_removed_when_pg_restore_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(
            backup_service.requests,
            "get",
            lambda *_a, **_kw: _FakeResponse(content=b"dump"),
        )
        base_run = _fake_pg_subprocess_run([])

        def failing_run(args: list[str], **kwargs: object) -> MagicMock:
            if args[0] == FAKE_PG_RESTORE and "--no-owner" in args:
                raise CalledProcessError(1, "pg_restore", stderr=b"boom")
            return base_run(args, **kwargs)

        monkeypatch.setattr(backup_service.subprocess, "run", failing_run)

        with pytest.raises(BackupError, match="pg_restore failed"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.dump", force=True
            )

        assert list(tmp_path.iterdir()) == []


class TestRetryTransientKoofrRequest:
    def test_succeeds_on_first_attempt(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(backup_service.time, "sleep", lambda _seconds: None)
        operation = MagicMock(return_value="ok")

        result = backup_service._retry_transient_koofr_request(operation)

        assert result == "ok"
        assert operation.call_count == 1

    def test_retries_then_succeeds(self, monkeypatch: pytest.MonkeyPatch):
        sleeps: list[float] = []
        monkeypatch.setattr(backup_service.time, "sleep", sleeps.append)
        operation = MagicMock(side_effect=[requests.ConnectionError("boom"), "ok"])

        result = backup_service._retry_transient_koofr_request(operation)

        assert result == "ok"
        assert operation.call_count == 2
        assert sleeps == [1.0]

    def test_gives_up_after_exhausting_attempts(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(backup_service.time, "sleep", lambda _seconds: None)
        operation = MagicMock(side_effect=requests.Timeout("timed out"))

        with pytest.raises(requests.Timeout):
            backup_service._retry_transient_koofr_request(operation)

        assert operation.call_count == 3
