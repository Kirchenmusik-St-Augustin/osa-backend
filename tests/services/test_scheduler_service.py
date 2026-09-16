import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.db.models.job_run import JobRun
from app.services.scheduler_service import get_scheduled_jobs

if TYPE_CHECKING:
    import pytest
    from sqlalchemy.orm import Session

_NEXT_RUN_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}, \d{2}:\d{2}$")
_ALWAYS_ON_JOB_ID = "purge_stale_booking_requests"
_PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP = {
    "notify_upcoming_booking_status",
    "purge_expired_password_reset_tokens",
    "purge_old_request_logs",
    "backup_koofr",
}


def test_includes_always_on_job_with_description(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    get_settings.cache_clear()

    jobs_by_id = {job.id: job for job in get_scheduled_jobs(db_session)}

    assert _ALWAYS_ON_JOB_ID in jobs_by_id
    assert jobs_by_id[_ALWAYS_ON_JOB_ID].description.strip() != ""


def test_includes_production_only_jobs_with_descriptions(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    get_settings.cache_clear()

    jobs_by_id = {job.id: job for job in get_scheduled_jobs(db_session)}

    assert jobs_by_id.keys() >= _PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP
    assert all(
        jobs_by_id[job_id].description.strip() != ""
        for job_id in _PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP
    )


def test_excludes_production_only_jobs_outside_production(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    get_settings.cache_clear()

    job_ids = {job.id for job in get_scheduled_jobs(db_session)}

    assert job_ids.isdisjoint(_PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP)


def test_next_run_is_formatted(db_session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    get_settings.cache_clear()

    job = next(
        job for job in get_scheduled_jobs(db_session) if job.id == _ALWAYS_ON_JOB_ID
    )

    assert _NEXT_RUN_PATTERN.match(job.next_run or "")


def test_trigger_display_only_lists_fields_that_are_actually_set(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    get_settings.cache_clear()

    jobs_by_id = {job.id: job for job in get_scheduled_jobs(db_session)}

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


class TestLastRun:
    """last_run is the one persisted field on an otherwise purely
    catalog-computed overview -- see app.services.job_run_service."""

    def test_last_run_is_none_when_the_job_has_never_run(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        get_settings.cache_clear()

        job = next(
            job for job in get_scheduled_jobs(db_session) if job.id == _ALWAYS_ON_JOB_ID
        )

        assert job.last_run is None

    def test_last_run_reflects_the_most_recent_job_runs_row(
        self, db_session: Session, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        get_settings.cache_clear()
        older_start = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
        newer_start = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
        db_session.add(
            JobRun(
                job_id=_ALWAYS_ON_JOB_ID,
                status="failure",
                started_at=older_start,
                finished_at=older_start + timedelta(seconds=1),
                output="stale run",
            )
        )
        db_session.add(
            JobRun(
                job_id=_ALWAYS_ON_JOB_ID,
                status="success",
                started_at=newer_start,
                finished_at=newer_start + timedelta(seconds=2),
                output=None,
            )
        )
        db_session.commit()

        job = next(
            job for job in get_scheduled_jobs(db_session) if job.id == _ALWAYS_ON_JOB_ID
        )

        assert job.last_run is not None
        assert job.last_run.status == "success"
        assert job.last_run.output is None
        assert job.last_run.started_at == newer_start
