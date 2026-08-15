import sqlite3
import tarfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
import requests

from app.services import backup_service
from app.services.backup_service import BackupError


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


def _make_sqlite_file(path: Path, *, marker: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE marker (value TEXT)")
    conn.execute("INSERT INTO marker VALUES (?)", (marker,))
    conn.commit()
    conn.close()


def _read_marker(path: Path) -> str:
    conn = sqlite3.connect(path)
    value = conn.execute("SELECT value FROM marker").fetchone()[0]
    conn.close()
    return str(value)


def _build_archive(*, arcname: str, source: Path) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.add(source, arcname=arcname)
    return buffer.getvalue()


class TestRunBackup:
    def test_uploads_a_valid_archive_with_stage_prefixed_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        db_path = tmp_path / "test.sqlite"
        _make_sqlite_file(db_path, marker="backup-me")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

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
        assert not archive_name.endswith("-manual.tar.gz")
        assert str(uploaded["url"]).endswith(archive_name)
        assert uploaded["auth"] == ("user", "pw")

        with tarfile.open(fileobj=BytesIO(uploaded["data"]), mode="r:gz") as tar:  # type: ignore[arg-type]
            assert tar.getnames() == ["test.sqlite"]
            extract_dir = tmp_path / "extracted"
            extract_dir.mkdir()
            tar.extractall(extract_dir, filter="data")
        assert _read_marker(extract_dir / "test.sqlite") == "backup-me"

    def test_manual_true_tags_the_filename_with_a_manual_suffix(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        db_path = tmp_path / "test.sqlite"
        _make_sqlite_file(db_path, marker="x")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(
            backup_service.requests,
            "put",
            lambda *_a, **_kw: _FakeResponse(status_code=200),
        )

        archive_name = backup_service.run_backup(manual=True)

        assert archive_name.endswith("-manual.tar.gz")
        assert backup_service._FILENAME_PATTERN.match(archive_name)

    def test_raises_for_a_non_sqlite_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@localhost/db")

        with pytest.raises(BackupError, match="SQLite"):
            backup_service.run_backup()

    def test_raises_when_koofr_upload_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        db_path = tmp_path / "test.sqlite"
        _make_sqlite_file(db_path, marker="x")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        def fake_put(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "boom"
            raise requests.ConnectionError(msg)

        monkeypatch.setattr(backup_service.requests, "put", fake_put)

        with pytest.raises(BackupError, match="upload failed"):
            backup_service.run_backup()

    def test_raises_when_koofr_credentials_are_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        db_path = tmp_path / "test.sqlite"
        _make_sqlite_file(db_path, marker="x")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.delenv("KOOFR_USER", raising=False)
        monkeypatch.delenv("KOOFR_PASSWORD", raising=False)

        with pytest.raises(BackupError, match="KOOFR_USER"):
            backup_service.run_backup()

    def test_uses_the_configured_app_timezone_not_utc_for_the_filename_timestamp(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """Regression for the reported bug: run_backup()'s filename stamp
        must match the Vienna wall-clock the backup_koofr scheduler trigger
        fires in (Settings.backup_hour/minute, app_timezone), not UTC --
        previously a UTC-stamped filename disagreed with the scheduler's
        own timezone by the current UTC offset."""
        db_path = tmp_path / "test.sqlite"
        _make_sqlite_file(db_path, marker="x")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
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
    <d:href>/dav/Koofr/Backups/osa-db/production-2024-01-02_10-00-00.tar.gz</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Tue, 02 Jan 2024 10:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2024-01-01_09-00-00.tar.gz</d:href>
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
            "production-2024-01-01_09-00-00.tar.gz",
            "production-2024-01-02_10-00-00.tar.gz",
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
    <d:href>/dav/Koofr/Backups/osa-db/development-2024-06-01_00-00-00.tar.gz</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Sat, 01 Jun 2024 00:00:00 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2024-01-01_00-00-00.tar.gz</d:href>
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
            "production-2024-01-01_00-00-00.tar.gz",
            "development-2024-06-01_00-00-00.tar.gz",
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

    def test_raises_when_propfind_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        def fake_request(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "timed out"
            raise requests.Timeout(msg)

        monkeypatch.setattr(backup_service.requests, "request", fake_request)

        with pytest.raises(BackupError, match="listing failed"):
            backup_service.list_backups()

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
    <d:href>/dav/Koofr/Backups/osa-db/production-2026-08-13_20-50-14-manual.tar.gz</d:href>
    <d:propstat><d:prop>
      <d:getlastmodified>Thu, 13 Aug 2026 20:50:14 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/dav/Koofr/Backups/osa-db/production-2026-08-14_03-00-00.tar.gz</d:href>
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
            "production-2026-08-13_20-50-14-manual.tar.gz",
            "production-2026-08-14_03-00-00.tar.gz",
        ]


class TestCleanupOldBackups:
    def test_deletes_only_entries_past_retention(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setenv("KOOFR_BACKUP_RETENTION_DAYS", "28")

        now = datetime.now(UTC)
        old_stamp = f"{(now - timedelta(days=30)):%Y-%m-%d_%H-%M-%S}"
        fresh_stamp = f"{(now - timedelta(days=1)):%Y-%m-%d_%H-%M-%S}"
        old_name = f"production-{old_stamp}.tar.gz"
        fresh_name = f"production-{fresh_stamp}.tar.gz"
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

        old_name = "production-2000-01-01_00-00-00.tar.gz"
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

        old_name = "production-2000-01-01_00-00-00.tar.gz"
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
        kept_name = "production-2026-07-17_03-00-01.tar.gz"
        deleted_name = "production-2026-07-17_02-59-59.tar.gz"
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
        monkeypatch.setenv("APP_ENVIRONMENT", "production")

        with pytest.raises(BackupError, match="force"):
            backup_service.run_restore()

    def test_raises_when_koofr_download_fails(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        target_path = tmp_path / "test.sqlite"
        _make_sqlite_file(target_path, marker="unchanged")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        def fake_get(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "connection reset"
            raise requests.ConnectionError(msg)

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        with pytest.raises(BackupError, match="download failed"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.tar.gz",
                force=True,
            )

        assert _read_marker(target_path) == "unchanged"

    def test_atomically_replaces_the_target_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        target_path = tmp_path / "test.sqlite"
        _make_sqlite_file(target_path, marker="old-value")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        replacement_db = tmp_path / "replacement.sqlite"
        _make_sqlite_file(replacement_db, marker="new-value")
        archive_content = _build_archive(arcname="test.sqlite", source=replacement_db)

        def fake_get(*_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse(status_code=200, content=archive_content)

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        backup_name = "production-2024-01-01_00-00-00.tar.gz"
        result = backup_service.run_restore(backup_name=backup_name, force=True)

        assert result == backup_name
        assert _read_marker(target_path) == "new-value"
        assert list(tmp_path.glob(".osa-restore-*")) == []

    def test_raises_when_archive_missing_expected_member(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        target_path = tmp_path / "test.sqlite"
        _make_sqlite_file(target_path, marker="unchanged")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        unrelated = tmp_path / "unrelated.txt"
        unrelated.write_text("nope")
        archive_content = _build_archive(arcname="unrelated.txt", source=unrelated)

        def fake_get(*_args: object, **_kwargs: object) -> _FakeResponse:
            return _FakeResponse(status_code=200, content=archive_content)

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        with pytest.raises(BackupError, match="did not contain"):
            backup_service.run_restore(
                backup_name="production-2024-01-01_00-00-00.tar.gz",
                force=True,
            )

        assert _read_marker(target_path) == "unchanged"

    def test_auto_selects_the_latest_backup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        target_path = tmp_path / "test.sqlite"
        _make_sqlite_file(target_path, marker="x")
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target_path}")
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")

        older = "production-2024-01-01_00-00-00.tar.gz"
        newest = "production-2024-06-01_00-00-00.tar.gz"
        monkeypatch.setattr(backup_service, "list_backups", lambda: [older, newest])

        replacement_db = tmp_path / "replacement.sqlite"
        _make_sqlite_file(replacement_db, marker="restored")
        archive_content = _build_archive(arcname="test.sqlite", source=replacement_db)
        requested_urls: list[str] = []

        def fake_get(url: str, **_kwargs: object) -> _FakeResponse:
            requested_urls.append(url)
            return _FakeResponse(status_code=200, content=archive_content)

        monkeypatch.setattr(backup_service.requests, "get", fake_get)

        result = backup_service.run_restore(force=True)

        assert result == newest
        assert requested_urls[0].endswith(newest)

    def test_rejects_a_malformed_backup_name_before_any_network_call(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        def fail_get(*_args: object, **_kwargs: object) -> _FakeResponse:
            msg = "no network call for an invalid backup name"
            raise AssertionError(msg)

        monkeypatch.setattr(backup_service.requests, "get", fail_get)

        with pytest.raises(BackupError, match="not a valid backup filename"):
            backup_service.run_restore(backup_name="../../etc/passwd")

    def test_raises_when_no_backups_exist_for_auto_select(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("KOOFR_USER", "user")
        monkeypatch.setenv("KOOFR_PASSWORD", "pw")
        monkeypatch.setattr(backup_service, "list_backups", list)

        with pytest.raises(BackupError, match="No backups found"):
            backup_service.run_restore(force=True)
