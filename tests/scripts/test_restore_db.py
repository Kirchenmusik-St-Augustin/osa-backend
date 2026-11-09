import sys
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.services.backup_service import BackupError
from scripts import restore_db


class TestMainList:
    def test_prints_each_backup_on_its_own_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        backups = ["a.dump", "b.dump"]
        monkeypatch.setattr(restore_db, "list_backups", lambda: backups)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--list"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "a.dump" in out
        assert "b.dump" in out

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
            return "restored.dump"

        monkeypatch.setattr(restore_db, "run_restore", fake_run_restore)
        monkeypatch.setattr(
            sys,
            "argv",
            ["restore_db.py", "--backup-name", "restored.dump", "--force", "--yes"],
        )

        restore_db.main()

        assert received == {"backup_name": "restored.dump", "force": True}
        assert "restored.dump" in capsys.readouterr().out

    def test_backup_error_exits_with_code_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def failing_restore(**_kwargs: object) -> str:
            msg = "restore in production requires --force"
            raise BackupError(msg)

        monkeypatch.setattr(restore_db, "run_restore", failing_restore)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--yes"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 1
        assert "requires --force" in capsys.readouterr().err


class TestMainListFailure:
    def test_a_listing_failure_is_reported_without_a_traceback(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        def failing_listing() -> list[str]:
            msg = "Koofr unreachable"
            raise BackupError(msg)

        monkeypatch.setattr(restore_db, "list_backups", failing_listing)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--list"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 1
        assert "ERROR: Koofr unreachable" in capsys.readouterr().err


class TestTypedConfirmation:
    @staticmethod
    def _prepare(monkeypatch: pytest.MonkeyPatch, restores: list[str | None]) -> None:
        def fake_run_restore(*, backup_name: str | None, **_options: object) -> str:
            restores.append(backup_name)
            return "restored.dump"

        monkeypatch.setattr(restore_db, "run_restore", fake_run_restore)
        monkeypatch.setattr(
            restore_db,
            "get_settings",
            lambda: SimpleNamespace(
                database_url=SecretStr("postgresql://u:p@db.example:5432/osa_live")
            ),
        )

    def test_the_target_and_the_backup_are_named_before_anything_is_replaced(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ):
        restores: list[str | None] = []
        self._prepare(monkeypatch, restores)
        monkeypatch.setattr("builtins.input", lambda _question: "osa_live")
        monkeypatch.setattr(
            sys, "argv", ["restore_db.py", "--backup-name", "old.dump", "--force"]
        )

        restore_db.main()

        err = capsys.readouterr().err
        assert "osa_live" in err
        assert "db.example" in err
        assert "old.dump" in err
        assert restores == ["old.dump"]

    @pytest.mark.parametrize("answer", ["", "yes", "osa", "OSA_LIVE"])
    def test_any_other_answer_aborts_without_restoring(
        self, monkeypatch: pytest.MonkeyPatch, answer: str
    ):
        restores: list[str | None] = []
        self._prepare(monkeypatch, restores)
        monkeypatch.setattr("builtins.input", lambda _question: answer)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--force"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 1
        assert restores == []

    def test_a_closed_input_aborts_without_restoring(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        restores: list[str | None] = []
        self._prepare(monkeypatch, restores)

        def closed_input(_question: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", closed_input)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--force"])

        with pytest.raises(SystemExit) as exc_info:
            restore_db.main()

        assert exc_info.value.code == 1
        assert restores == []

    def test_yes_skips_the_confirmation(self, monkeypatch: pytest.MonkeyPatch):
        restores: list[str | None] = []
        self._prepare(monkeypatch, restores)

        def unexpected_input(_question: str) -> str:
            msg = "must not ask"
            raise AssertionError(msg)

        monkeypatch.setattr("builtins.input", unexpected_input)
        monkeypatch.setattr(sys, "argv", ["restore_db.py", "--force", "--yes"])

        restore_db.main()

        assert restores == [None]
