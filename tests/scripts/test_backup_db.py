import sys

import pytest

from app.services.backup_service import BackupError
from scripts import backup_db


class TestMainList:
    def test_prints_each_backup_on_its_own_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setattr(backup_db, "list_backups", lambda: ["a.dump", "b.dump"])
        monkeypatch.setattr(sys, "argv", ["backup_db.py", "--list"])

        with pytest.raises(SystemExit) as exc_info:
            backup_db.main()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "a.dump" in out
        assert "b.dump" in out

    def test_reports_when_no_backups_exist(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setattr(backup_db, "list_backups", list)
        monkeypatch.setattr(sys, "argv", ["backup_db.py", "--list"])

        with pytest.raises(SystemExit) as exc_info:
            backup_db.main()

        assert exc_info.value.code == 0
        assert "No backups found" in capsys.readouterr().err


class TestMainBackup:
    def test_plain_run_creates_a_backup_and_skips_cleanup(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        cleanup_called = False

        def fake_cleanup(**_kwargs: object) -> list[str]:
            nonlocal cleanup_called
            cleanup_called = True
            return []

        monkeypatch.setattr(backup_db, "run_backup", lambda: "new.dump")
        monkeypatch.setattr(backup_db, "cleanup_old_backups", fake_cleanup)
        monkeypatch.setattr(sys, "argv", ["backup_db.py"])

        backup_db.main()

        assert "new.dump" in capsys.readouterr().out
        assert cleanup_called is False

    def test_cleanup_flag_runs_cleanup_afterward(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setattr(backup_db, "run_backup", lambda: "new.dump")
        monkeypatch.setattr(
            backup_db, "cleanup_old_backups", lambda **_kwargs: ["old.dump"]
        )
        monkeypatch.setattr(sys, "argv", ["backup_db.py", "--cleanup"])

        backup_db.main()

        out = capsys.readouterr().out
        assert "new.dump" in out
        assert "old.dump" in out

    def test_cleanup_dry_run_is_passed_through(self, monkeypatch: pytest.MonkeyPatch):
        received: dict[str, bool] = {}

        def fake_cleanup(*, dry_run: bool = False) -> list[str]:
            received["dry_run"] = dry_run
            return []

        monkeypatch.setattr(backup_db, "run_backup", lambda: "new.dump")
        monkeypatch.setattr(backup_db, "cleanup_old_backups", fake_cleanup)
        monkeypatch.setattr(sys, "argv", ["backup_db.py", "--cleanup", "--dry-run"])

        backup_db.main()

        assert received["dry_run"] is True

    def test_backup_error_exits_with_code_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def failing_backup() -> str:
            msg = "upload failed"
            raise BackupError(msg)

        monkeypatch.setattr(backup_db, "run_backup", failing_backup)
        monkeypatch.setattr(sys, "argv", ["backup_db.py"])

        with pytest.raises(SystemExit) as exc_info:
            backup_db.main()

        assert exc_info.value.code == 1
        assert "upload failed" in capsys.readouterr().err


class TestMainRefusals:
    def test_dry_run_without_cleanup_is_refused_before_anything_is_uploaded(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        backups_made: list[str] = []
        monkeypatch.setattr(
            backup_db, "run_backup", lambda: backups_made.append("x") or "x.dump"
        )
        monkeypatch.setattr(sys, "argv", ["backup_db.py", "--dry-run"])

        with pytest.raises(SystemExit) as exc_info:
            backup_db.main()

        assert exc_info.value.code == 2
        assert "--cleanup" in capsys.readouterr().err
        assert backups_made == []

    def test_a_failing_listing_is_reported_without_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def failing_listing() -> list[str]:
            msg = "Koofr unreachable"
            raise BackupError(msg)

        monkeypatch.setattr(backup_db, "list_backups", failing_listing)
        monkeypatch.setattr(sys, "argv", ["backup_db.py", "--list"])

        with pytest.raises(SystemExit) as exc_info:
            backup_db.main()

        assert exc_info.value.code == 1
        assert "ERROR: Koofr unreachable" in capsys.readouterr().err

    def test_a_failing_cleanup_after_a_successful_backup_exits_with_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def failing_cleanup(**_kwargs: object) -> list[str]:
            msg = "delete refused"
            raise BackupError(msg)

        monkeypatch.setattr(backup_db, "run_backup", lambda: "new.dump")
        monkeypatch.setattr(backup_db, "cleanup_old_backups", failing_cleanup)
        monkeypatch.setattr(sys, "argv", ["backup_db.py", "--cleanup"])

        with pytest.raises(SystemExit) as exc_info:
            backup_db.main()

        captured = capsys.readouterr()
        assert exc_info.value.code == 1
        assert "Backup complete: new.dump" in captured.out
        assert "ERROR: delete refused" in captured.err
