from app.core.config import get_settings
from app.core.datetime_utils import get_app_timezone
from app.core.job_serialization import dumps_job, loads_job
from app.worker.cron_config import CronSchedule, build_cron_catalog
from app.worker.scheduled_jobs import purge_stale_booking_requests_task
from app.worker.settings import _JOB_COROUTINES, WorkerSettings, _build_cron_job


def test_functions_is_non_empty():
    # arq's Worker.__init__ raises RuntimeError at startup if this were
    # ever empty (see WorkerSettings' own docstring) -- a smoke test
    # against silently losing every on-demand job registration.
    assert len(WorkerSettings.functions) == 7


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


def test_job_completion_wait_gives_in_flight_jobs_a_real_shutdown_grace_period():
    # arq's own default (0) cancels an in-flight job the instant a stop
    # signal arrives instead of letting it finish -- fatal for a job
    # mid-pg_dump/pg_restore (backup_koofr, downsync). Guards against a
    # future refactor silently dropping this back to arq's default.
    assert WorkerSettings.job_completion_wait > 0


def test_finished_jobs_keep_no_result_so_one_time_links_do_not_stay_in_valkey():
    assert WorkerSettings.keep_result == 0


def test_heartbeat_is_refreshed_often_enough_for_the_container_health_check():
    # `arq --check` fails while the heartbeat key is older than this interval;
    # arq's default (3600 seconds) would leave a 30-second probe failing for
    # most of every hour. The probe interval in osa-deploy's worker Quadlet
    # is 30 seconds, so the heartbeat must not be slower than that.
    assert WorkerSettings.health_check_interval <= 30


def test_worker_reads_jobs_with_the_serializer_the_web_side_enqueues_with():
    # The queue must never fall back to arq's pickle default on either side.
    assert WorkerSettings.job_serializer is dumps_job
    assert WorkerSettings.job_deserializer is loads_job
