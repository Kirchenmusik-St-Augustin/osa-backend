from app.core.config import get_settings
from app.core.datetime_utils import get_app_timezone
from app.worker.cron_config import CronSchedule, build_cron_catalog
from app.worker.scheduled_jobs import purge_stale_booking_requests_task
from app.worker.settings import _JOB_COROUTINES, WorkerSettings, _build_cron_job


def test_functions_is_non_empty():
    # arq's Worker.__init__ raises RuntimeError at startup if this were
    # ever empty (see WorkerSettings' own docstring) -- a smoke test
    # against silently losing every on-demand job registration.
    assert len(WorkerSettings.functions) == 5


def test_cron_jobs_is_non_empty_under_the_test_suite_s_default_environment():
    # purge_stale_booking_requests is active in every environment
    # (including "test", the default APP_ENVIRONMENT this whole suite
    # runs under -- see conftest.py), so this is never empty regardless of
    # which environment happened to be active when this module was first
    # imported.
    assert len(WorkerSettings.cron_jobs) >= 1


def test_job_coroutines_dict_covers_every_schedule_job_id():
    # Would raise KeyError inside _build_cron_job() at import time if a
    # future cron_config.py addition forgot its matching entry here --
    # this test turns that into an assertion failure with a clear message
    # instead of an import-time crash.
    schedule_job_ids = {
        schedule.job_id for schedule in build_cron_catalog(get_settings())
    }
    assert schedule_job_ids <= _JOB_COROUTINES.keys()


def test_build_cron_job_maps_schedule_fields_onto_a_real_cronjob():
    schedule = CronSchedule(
        job_id="purge_stale_booking_requests",
        description="irrelevant for this test",
        active=True,
        weekday="sun",
        hour=2,
        minute=15,
    )

    cron_job = _build_cron_job(schedule)

    assert cron_job.job_id == "purge_stale_booking_requests"
    assert cron_job.weekday == "sun"
    assert cron_job.hour == 2
    assert cron_job.minute == 15
    assert cron_job.coroutine is purge_stale_booking_requests_task


def test_worker_settings_timezone_matches_app_timezone():
    assert WorkerSettings.timezone == get_app_timezone()
