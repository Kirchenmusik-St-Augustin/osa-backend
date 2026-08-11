import sys

import pytest

from app.services.backup_service import BackupError
from scripts import restore_db


class TestMainList:
    def test_prints_each_backup_on_its_own_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        backups = ["a.tar.gz", "b.tar.gz"]
        monkeypatch.setattr(restore_db, "list_backups", lambda: backups)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--list"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "a.tar.gz" in out
        assert "b.tar.gz" in out

    def test_reports_when_no_backups_exist(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        monkeypatch.setattr(restore_db, "list_backups", list)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--list"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 0
        assert "No backups found" in capsys.readouterr().err


class TestMainRestore:
    def test_success_prints_the_restored_backup_name(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        received: dict[str, object] = {}

        def fake_run_restore(*, backup_name: str | None, force: bool) -> str:
            received["backup_name"] = backup_name
            received["force"] = force
            return "restored.tar.gz"

        monkeypatch.setattr(restore_db, "run_restore", fake_run_restore)
        monkeypatch.setattr(
            sys,
            "argv",
            ["restore_db.py", "--backup-name", "restored.tar.gz", "--force"],
        )

        restore_db.main()

        assert received == {"backup_name": "restored.tar.gz", "force": True}
        assert "restored.tar.gz" in capsys.readouterr().out

    def test_backup_error_exits_with_code_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def failing_restore(**_kwargs: object) -> str:
            msg = "restore in production requires --force"
            raise BackupError(msg)

        monkeypatch.setattr(restore_db, "run_restore", failing_restore)
        monkeypatch.setattr(sys, "argv", ["restore_db.py"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 1
        assert "requires --force" in capsys.readouterr().err
