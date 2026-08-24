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
