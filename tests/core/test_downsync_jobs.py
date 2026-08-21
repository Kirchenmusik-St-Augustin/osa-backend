import logging

import pytest

from app.services import downsync_jobs
from app.services.backup_service import BackupError


class TestJobDownsync:
    def test_success_restores_the_latest_production_backup(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        calls: list[tuple[str, object]] = []

        def fake_list_backups(**kwargs: object) -> list[str]:
            calls.append(("list_backups", kwargs["stage"]))
            return [
                "production-2024-01-01_00-00-00.tar.gz",
                "production-2024-06-01_00-00-00.tar.gz",
            ]

        def fake_run_restore(**kwargs: object) -> str:
            backup_name = kwargs["backup_name"]
            calls.append(("run_restore", backup_name))
            return str(backup_name)

        monkeypatch.setattr(downsync_jobs, "list_backups", fake_list_backups)
        monkeypatch.setattr(downsync_jobs, "run_restore", fake_run_restore)

        downsync_jobs.job_downsync()

        assert calls == [
            ("list_backups", "production"),
            ("run_restore", "production-2024-06-01_00-00-00.tar.gz"),
        ]

    def test_never_runs_in_production_even_if_registration_guard_is_bypassed(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "production")

        def unexpected_list_backups(**_kwargs: object) -> list[str]:
            msg = "job_downsync must never call list_backups() in production"
            raise AssertionError(msg)

        monkeypatch.setattr(downsync_jobs, "list_backups", unexpected_list_backups)

        with caplog.at_level(logging.ERROR):
            downsync_jobs.job_downsync()

        assert "production" in caplog.text.lower()

    def test_skips_and_logs_when_no_production_backup_exists_yet(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        monkeypatch.setattr(downsync_jobs, "list_backups", lambda **_kwargs: [])

        def unexpected_run_restore(**_kwargs: object) -> str:
            msg = "run_restore must not run when no production backup exists"
            raise AssertionError(msg)

        monkeypatch.setattr(downsync_jobs, "run_restore", unexpected_run_restore)

        with caplog.at_level(logging.INFO):
            downsync_jobs.job_downsync()

        assert "no production backup" in caplog.text.lower()

    def test_list_backups_failure_is_caught_and_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "test")

        def failing_list_backups(**_kwargs: object) -> list[str]:
            msg = "Koofr directory listing failed"
            raise BackupError(msg)

        monkeypatch.setattr(downsync_jobs, "list_backups", failing_list_backups)

        with caplog.at_level(logging.ERROR):
            downsync_jobs.job_downsync()

        assert "could not list backups" in caplog.text.lower()

    def test_run_restore_failure_is_caught_and_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        monkeypatch.setattr(
            downsync_jobs,
            "list_backups",
            lambda **_kwargs: ["production-2024-01-01_00-00-00.tar.gz"],
        )

        def failing_run_restore(**_kwargs: object) -> str:
            msg = "Koofr download failed"
            raise BackupError(msg)

        monkeypatch.setattr(downsync_jobs, "run_restore", failing_run_restore)

        with caplog.at_level(logging.ERROR):
            downsync_jobs.job_downsync()

        assert "scheduled downsync failed" in caplog.text.lower()
