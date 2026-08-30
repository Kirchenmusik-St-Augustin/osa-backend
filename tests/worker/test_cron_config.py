import pytest

from app.core.config import get_settings
from app.worker.cron_config import build_cron_catalog

_ALWAYS_ON_JOB_ID = "purge_stale_booking_requests"
_PRODUCTION_ONLY_JOB_IDS = {
    "notify_upcoming_booking_status",
    "purge_expired_password_reset_tokens",
    "purge_old_request_logs",
}


def _active_job_ids() -> set[str]:
    get_settings.cache_clear()
    settings = get_settings()
    return {
        schedule.job_id for schedule in build_cron_catalog(settings) if schedule.active
    }


def test_always_on_job_is_active_regardless_of_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    assert _ALWAYS_ON_JOB_ID in _active_job_ids()

    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    assert _ALWAYS_ON_JOB_ID in _active_job_ids()


def test_production_only_jobs_active_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    assert _active_job_ids() >= _PRODUCTION_ONLY_JOB_IDS


def test_production_only_jobs_inactive_outside_production(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    assert _PRODUCTION_ONLY_JOB_IDS.isdisjoint(_active_job_ids())


def test_backup_koofr_active_in_production_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    assert "backup_koofr" in _active_job_ids()


def test_backup_koofr_inactive_outside_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    assert "backup_koofr" not in _active_job_ids()


def test_backup_koofr_inactive_when_disabled_even_in_production(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "false")
    assert "backup_koofr" not in _active_job_ids()


def test_downsync_active_outside_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    assert "downsync" in _active_job_ids()


def test_downsync_inactive_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    assert "downsync" not in _active_job_ids()


def test_downsync_runs_one_hour_after_the_backup_hour(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("BACKUP_HOUR", "3")
    monkeypatch.setenv("BACKUP_MINUTE", "15")
    get_settings.cache_clear()

    catalog = build_cron_catalog(get_settings())
    downsync = next(schedule for schedule in catalog if schedule.job_id == "downsync")

    assert downsync.hour == 4
    assert downsync.minute == 15


def test_downsync_wraps_the_hour_at_the_day_boundary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("BACKUP_HOUR", "23")
    get_settings.cache_clear()

    catalog = build_cron_catalog(get_settings())
    downsync = next(schedule for schedule in catalog if schedule.job_id == "downsync")

    assert downsync.hour == 0


def test_purge_expired_password_reset_tokens_runs_sunday_nights(
    monkeypatch: pytest.MonkeyPatch,
):
    # arq's weekday spelling matches APScheduler's here by coincidence
    # ('sun' is identical in both) -- see cron_config.py's own docstring
    # for the 'tues'/'thurs' trap that would NOT be identical.
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    get_settings.cache_clear()

    catalog = build_cron_catalog(get_settings())
    job = next(
        schedule
        for schedule in catalog
        if schedule.job_id == "purge_expired_password_reset_tokens"
    )

    assert job.weekday == "sun"
    assert job.hour == 2
    assert job.minute == 0


def test_every_schedule_has_a_non_empty_description(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    get_settings.cache_clear()

    for schedule in build_cron_catalog(get_settings()):
        assert schedule.description.strip() != ""
