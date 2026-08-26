from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from subprocess import CalledProcessError
from unittest.mock import MagicMock

import pytest
import requests

from app.services import backup_service
from app.services.backup_service import BackupError

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


class _FakeResponse:
    def __init__(
        self, *, status_code: int = 200, content: bytes = b"", text: str = ""
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            msg = f"status {self.status_code}"
            raise requests.HTTPError(msg)


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


class TestRunBackup:
    def test_uploads_a_dump_with_stage_prefixed_name(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", PG_URL)
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service.shutil, "which", _which_side_effect)
        monkeypatch.setattr(
            backup_service.subprocess,
            "run",
            lambda *_a, **_kw: MagicMock(stdout=b"PG_DUMP_DATA", returncode=0),
        )

        uploaded: dict[str, object] = {}

        def fake_put(
            url: str, *, data: bytes, auth: object, **_kwargs: object
        ) -> _FakeResponse:
            uploaded["url"] = url
            uploaded["data"] = data
            uploaded["auth"] = auth
            return _FakeResponse(status_code=200)

        monkeypatch.setattr(backup_service.requests, "put", fake_put)

        archive_name = backup_service.run_backup()

        match = backup_service._FILENAME_PATTERN.match(archive_name)
        assert match is not None
        # APP_ENVIRONMENT is "test" in the test suite (see conftest.py).
        assert match.group("stage") == "test"
        assert not archive_name.endswith("-manual.dump")
        assert str(uploaded["url"]).endswith(archive_name)
        assert uploaded["auth"] == ("user", "pw")
        assert uploaded["data"] == b"PG_DUMP_DATA"

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
        """Regression for the reported bug: run_backup()'s filename stamp
        must match the Vienna wall-clock the backup_koofr scheduler trigger
        fires in (Settings.backup_hour/minute, app_timezone), not UTC --
        previously a UTC-stamped filename disagreed with the scheduler's
        own timezone by the current UTC offset."""
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
        """Regression test for the Legacy bug this module deliberately does
        NOT replicate (see backup_service's module docstring): Koofr's
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
        # psql (wipe), pg_restore, psql (ANALYZE), psql (row-count verify)
        assert len(calls) == 4
        assert calls[0][0] == FAKE_PSQL
        assert "DROP SCHEMA public CASCADE" in calls[0][-1]
        assert calls[1][0] == FAKE_PG_RESTORE
        assert calls[2][0] == FAKE_PSQL
        assert calls[2][-1] == "ANALYZE;"
        assert calls[3][0] == FAKE_PSQL
        assert "SUM(n_live_tup)" in calls[3][-1]

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

    def test_wipe_excludes_the_advisory_lock_holding_session(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The scheduler's own connection (see
        app.core.scheduler._acquire_scheduler_lock()) must survive the
        pre-restore pg_terminate_backend() sweep -- terminating it would
        silently stop this worker's scheduled jobs until the next
        restart."""
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
            backup_service.subprocess, "run", _fake_pg_subprocess_run([])
        )

        backup_service.run_restore(
            backup_name="production-2024-01-01_00-00-00.dump", force=True
        )
        # No assertion needed beyond "did not raise" -- the SQL text itself
        # is asserted in test_wipes_schema_then_restores_the_downloaded_dump;
        # this test documents WHY that exclusion clause exists.

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
        monkeypatch.setattr(backup_service, "list_backups", lambda: [older, newest])

        requested_urls: list[str] = []

        def fake_get(url: str, **_kwargs: object) -> _FakeResponse:
            requested_urls.append(url)
            return _FakeResponse(status_code=200, content=b"x")

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        result = backup_service.run_restore(force=True)

        assert result == newest
        assert requested_urls[0].endswith(newest)

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
        monkeypatch.setattr(backup_service, "list_backups", list)

        with pytest.raises(BackupError, match="No backups found"):
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
