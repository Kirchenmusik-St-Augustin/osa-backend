import logging
from unittest.mock import Mock

import pytest

from app.services import backup_jobs
from app.services.backup_service import BackupError


@pytest.fixture(autouse=True)
def mock_record_job_run(monkeypatch: pytest.MonkeyPatch) -> Mock:
    """job_backup_koofr() self-reports via record_job_run() -- mocked at
    backup_jobs' own import site (same pattern as run_backup/
    cleanup_old_backups below), never touching a real DB session in this
    otherwise pure unit-test file."""
    mock = Mock()
    monkeypatch.setattr(backup_jobs, "record_job_run", mock)
    return mock


class TestJobBackupKoofr:
    def test_success_runs_backup_then_cleanup(
        self, monkeypatch: pytest.MonkeyPatch, mock_record_job_run: Mock
    ):
        calls: list[str] = []

        def fake_run_backup() -> str:
            calls.append("backup")
            return "archive.dump"

        def fake_cleanup() -> list[str]:
            calls.append("cleanup")
            return []

        monkeypatch.setattr(backup_jobs, "run_backup", fake_run_backup)
        monkeypatch.setattr(backup_jobs, "cleanup_old_backups", fake_cleanup)

        backup_jobs.job_backup_koofr()

        assert calls == ["backup", "cleanup"]
        mock_record_job_run.assert_called_once()
        _job_id, _started_at = mock_record_job_run.call_args.args
        assert _job_id == "backup_koofr"
        assert mock_record_job_run.call_args.kwargs == {
            "status": "success",
            "output": None,
        }

    def test_success_logs_when_cleanup_actually_deleted_something(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        mock_record_job_run: Mock,
    ):
        monkeypatch.setattr(backup_jobs, "run_backup", lambda: "archive.dump")
        monkeypatch.setattr(
            backup_jobs, "cleanup_old_backups", lambda: ["old-1.dump", "old-2.dump"]
        )

        with caplog.at_level(logging.INFO):
            backup_jobs.job_backup_koofr()

        assert "Cleaned up 2 expired" in caplog.text
        assert mock_record_job_run.call_args.kwargs == {
            "status": "success",
            "output": "Cleaned up 2 expired backup(s).",
        }

    def test_backup_failure_skips_cleanup_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        mock_record_job_run: Mock,
    ):
        def failing_backup() -> str:
            msg = "upload failed"
            raise BackupError(msg)

        def unexpected_cleanup() -> list[str]:
            msg = "cleanup must not run when backup itself failed"
            raise AssertionError(msg)

        monkeypatch.setattr(backup_jobs, "run_backup", failing_backup)
        monkeypatch.setattr(backup_jobs, "cleanup_old_backups", unexpected_cleanup)

        with caplog.at_level(logging.ERROR):
            backup_jobs.job_backup_koofr()

        assert "backup failed" in caplog.text.lower()
        assert mock_record_job_run.call_args.kwargs == {
            "status": "failure",
            "output": "upload failed",
        }

    def test_cleanup_failure_still_counts_backup_as_successful(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        mock_record_job_run: Mock,
    ):
        monkeypatch.setattr(backup_jobs, "run_backup", lambda: "archive.dump")

        def failing_cleanup() -> list[str]:
            msg = "delete failed"
            raise BackupError(msg)

        monkeypatch.setattr(backup_jobs, "cleanup_old_backups", failing_cleanup)

        with caplog.at_level(logging.ERROR):
            backup_jobs.job_backup_koofr()

        assert "cleanup failed" in caplog.text.lower()
        assert "archive.dump" in caplog.text
        # Overall success, not failure -- the backup itself (this job's
        # actual safety-net purpose) succeeded, only retention housekeeping
        # failed afterward. output records the caveat.
        recorded = mock_record_job_run.call_args.kwargs
        assert recorded["status"] == "success"
        assert "archive.dump" in recorded["output"]
        assert "delete failed" in recorded["output"]
