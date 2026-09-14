import asyncio
from unittest.mock import Mock, patch

import pytest

from app.worker import scheduled_jobs

# Patched at this module's own import site (app.worker.scheduled_jobs),
# not the underlying app.services module -- `from ... import x` copies the
# name into this module's namespace, same convention already used
# throughout the rest of this test suite for router-level patches.
_WRAPPERS_AND_TARGETS = [
    (scheduled_jobs.purge_stale_booking_requests_task, "purge_stale_booking_requests"),
    (
        scheduled_jobs.notify_upcoming_booking_status_task,
        "notify_upcoming_booking_status",
    ),
    (
        scheduled_jobs.purge_expired_password_reset_tokens_task,
        "purge_expired_password_reset_tokens",
    ),
    (scheduled_jobs.purge_old_request_logs_task, "purge_old_request_logs"),
    (scheduled_jobs.backup_koofr_task, "job_backup_koofr"),
    (scheduled_jobs.downsync_task, "job_downsync"),
]

# The four simple, single-exit-point job bodies that go through
# _run_and_record()'s generic wrapper -- backup_koofr_task/downsync_task
# are deliberately excluded (see _run_and_record's own docstring): their
# underlying job bodies self-report via record_job_run() instead.
_RECORDED_WRAPPERS_AND_TARGETS = [
    (
        scheduled_jobs.purge_stale_booking_requests_task,
        "purge_stale_booking_requests",
        "purge_stale_booking_requests",
    ),
    (
        scheduled_jobs.notify_upcoming_booking_status_task,
        "notify_upcoming_booking_status",
        "notify_upcoming_booking_status",
    ),
    (
        scheduled_jobs.purge_expired_password_reset_tokens_task,
        "purge_expired_password_reset_tokens",
        "purge_expired_password_reset_tokens",
    ),
    (
        scheduled_jobs.purge_old_request_logs_task,
        "purge_old_request_logs",
        "purge_old_request_logs",
    ),
]


def test_every_wrapper_calls_its_underlying_job_body_exactly_once():
    for wrapper, target_name in _WRAPPERS_AND_TARGETS:
        with patch.object(scheduled_jobs, target_name) as mock_job:
            asyncio.run(wrapper({}))
            mock_job.assert_called_once_with()


class TestRunAndRecord:
    """_run_and_record() is the shared wrapper behind the four simple job
    tasks -- exercised once per wrapper via the parametrized job_id/target
    pairs above, rather than duplicating both branches four times over."""

    @pytest.fixture(autouse=True)
    def mock_record_job_run(self, monkeypatch: pytest.MonkeyPatch) -> Mock:
        mock = Mock()
        monkeypatch.setattr(scheduled_jobs, "record_job_run", mock)
        return mock

    @pytest.mark.parametrize(
        ("wrapper", "target_name", "job_id"), _RECORDED_WRAPPERS_AND_TARGETS
    )
    def test_records_success_when_the_job_body_returns_normally(
        self, wrapper, target_name: str, job_id: str, mock_record_job_run: Mock
    ):
        with patch.object(scheduled_jobs, target_name):
            asyncio.run(wrapper({}))

        mock_record_job_run.assert_called_once()
        recorded_job_id, _started_at = mock_record_job_run.call_args.args
        assert recorded_job_id == job_id
        assert mock_record_job_run.call_args.kwargs == {
            "status": "success",
            "output": None,
        }

    @pytest.mark.parametrize(
        ("wrapper", "target_name", "job_id"), _RECORDED_WRAPPERS_AND_TARGETS
    )
    def test_records_failure_and_reraises_when_the_job_body_raises(
        self, wrapper, target_name: str, job_id: str, mock_record_job_run: Mock
    ):
        with (
            patch.object(scheduled_jobs, target_name, side_effect=ValueError("boom")),
            pytest.raises(ValueError, match="boom"),
        ):
            asyncio.run(wrapper({}))

        mock_record_job_run.assert_called_once()
        recorded_job_id, _started_at = mock_record_job_run.call_args.args
        assert recorded_job_id == job_id
        assert mock_record_job_run.call_args.kwargs["status"] == "failure"
        assert "ValueError: boom" in mock_record_job_run.call_args.kwargs["output"]

    def test_backup_and_downsync_tasks_never_call_record_job_run_directly(
        self, mock_record_job_run: Mock
    ):
        """job_backup_koofr/job_downsync self-report their own outcome
        (see app.services.backup_jobs/downsync_jobs) -- the wrapper must
        not additionally record a run for either of them."""
        with (
            patch.object(scheduled_jobs, "job_backup_koofr"),
            patch.object(scheduled_jobs, "job_downsync"),
        ):
            asyncio.run(scheduled_jobs.backup_koofr_task({}))
            asyncio.run(scheduled_jobs.downsync_task({}))

        mock_record_job_run.assert_not_called()
