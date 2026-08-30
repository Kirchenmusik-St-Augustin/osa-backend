import asyncio
from unittest.mock import patch

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


def test_every_wrapper_calls_its_underlying_job_body_exactly_once():
    for wrapper, target_name in _WRAPPERS_AND_TARGETS:
        with patch.object(scheduled_jobs, target_name) as mock_job:
            asyncio.run(wrapper({}))
            mock_job.assert_called_once_with()
