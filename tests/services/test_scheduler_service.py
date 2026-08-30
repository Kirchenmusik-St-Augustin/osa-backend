import re

import pytest

from app.core.config import get_settings
from app.services.scheduler_service import get_scheduled_jobs

_NEXT_RUN_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}, \d{2}:\d{2}$")
_ALWAYS_ON_JOB_ID = "purge_stale_booking_requests"
_PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP = {
    "notify_upcoming_booking_status",
    "purge_expired_password_reset_tokens",
    "purge_old_request_logs",
    "backup_koofr",
}


def test_includes_always_on_job_with_description(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    get_settings.cache_clear()

    jobs_by_id = {job.id: job for job in get_scheduled_jobs()}

    assert _ALWAYS_ON_JOB_ID in jobs_by_id
    assert jobs_by_id[_ALWAYS_ON_JOB_ID].description.strip() != ""


def test_includes_production_only_jobs_with_descriptions(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    get_settings.cache_clear()

    jobs_by_id = {job.id: job for job in get_scheduled_jobs()}

    assert jobs_by_id.keys() >= _PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP
    assert all(
        jobs_by_id[job_id].description.strip() != ""
        for job_id in _PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP
    )


def test_excludes_production_only_jobs_outside_production(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    get_settings.cache_clear()

    job_ids = {job.id for job in get_scheduled_jobs()}

    assert job_ids.isdisjoint(_PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP)


def test_next_run_is_formatted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    get_settings.cache_clear()

    job = next(job for job in get_scheduled_jobs() if job.id == _ALWAYS_ON_JOB_ID)

    assert _NEXT_RUN_PATTERN.match(job.next_run or "")


def test_trigger_display_only_lists_fields_that_are_actually_set(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    get_settings.cache_clear()

    jobs_by_id = {job.id: job for job in get_scheduled_jobs()}

    # purge_stale_booking_requests only sets minute -- month/day/weekday/
    # hour/second must not appear in its trigger string.
    always_on_trigger = jobs_by_id[_ALWAYS_ON_JOB_ID].trigger
    assert "minute=" in always_on_trigger
    assert "hour=" not in always_on_trigger
    assert "weekday=" not in always_on_trigger

    # purge_expired_password_reset_tokens sets weekday, hour, and minute.
    weekly_trigger = jobs_by_id["purge_expired_password_reset_tokens"].trigger
    assert "weekday='sun'" in weekly_trigger
    assert "hour='2'" in weekly_trigger
    assert "minute='0'" in weekly_trigger
