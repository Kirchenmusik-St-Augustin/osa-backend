from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from app.db.models.job_run import JobRun
from app.services import permission_service
from tests.login import login_headers

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class TestPermissionGuard:
    def test_list_jobs_requires_authentication(self, client):
        response = client.get("/administrator/scheduler/jobs")
        assert response.status_code == 401

    def test_list_jobs_rejects_non_administrator(self, client, make_user):
        headers = login_headers(client, make_user)
        response = client.get("/administrator/scheduler/jobs", headers=headers)
        assert response.status_code == 403

    def test_list_jobs_allows_administrator(self, client, make_user):
        headers = login_headers(client, make_user, administrator=True)
        response = client.get("/administrator/scheduler/jobs", headers=headers)
        assert response.status_code == 200

    def test_trigger_backup_requires_authentication(self, client):
        response = client.post("/administrator/scheduler/backup/trigger")
        assert response.status_code == 401

    def test_trigger_backup_rejects_non_administrator(self, client, make_user):
        headers = login_headers(client, make_user)
        response = client.post(
            "/administrator/scheduler/backup/trigger", headers=headers
        )
        assert response.status_code == 403

    def test_trigger_downsync_requires_authentication(self, client):
        response = client.post("/administrator/scheduler/downsync/trigger")
        assert response.status_code == 401

    def test_trigger_downsync_rejects_non_administrator(self, client, make_user):
        headers = login_headers(client, make_user)
        response = client.post(
            "/administrator/scheduler/downsync/trigger", headers=headers
        )
        assert response.status_code == 403


class TestTriggerNeedsItsOwnPermission:
    """A role that may only view the scheduler must not start the manual
    backup or the downsync."""

    @pytest.fixture
    def view_only_headers(self, client, make_user, monkeypatch) -> dict[str, str]:
        headers = login_headers(client, make_user, administrator=True)
        monkeypatch.setattr(
            permission_service,
            "PERMISSION_RULES",
            [
                rule
                for rule in permission_service.PERMISSION_RULES
                if rule.permission != "schedulerTrigger"
            ],
        )
        return headers

    def test_the_job_list_stays_available(self, client, view_only_headers):
        response = client.get(
            "/administrator/scheduler/jobs", headers=view_only_headers
        )

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "path",
        [
            "/administrator/scheduler/backup/trigger",
            "/administrator/scheduler/downsync/trigger",
        ],
    )
    def test_the_trigger_is_refused_without_queueing_the_job(
        self, client, view_only_headers, path, fake_arq_pool
    ):
        response = client.post(path, headers=view_only_headers)

        assert response.status_code == 403
        fake_arq_pool.enqueue_job.assert_not_called()


def test_returns_registered_jobs_with_expected_shape(client, make_user):
    # purge_stale_booking_requests is active in every environment, so this
    # is always non-empty regardless of APP_ENVIRONMENT.
    headers = login_headers(client, make_user, administrator=True)

    response = client.get("/administrator/scheduler/jobs", headers=headers)

    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) >= 1
    for job in jobs:
        assert set(job.keys()) == {
            "id",
            "name",
            "trigger",
            "next_run",
            "description",
            "last_run",
        }
        assert job["last_run"] is None


def test_hides_production_only_jobs_outside_production(client, make_user):
    headers = login_headers(client, make_user, administrator=True)

    response = client.get("/administrator/scheduler/jobs", headers=headers)

    assert response.status_code == 200
    job_ids = {job["id"] for job in response.json()}
    assert "purge_stale_booking_requests" in job_ids
    assert "downsync" in job_ids
    assert "backup_koofr" not in job_ids
    assert "notify_upcoming_booking_status" not in job_ids
    assert "purge_expired_password_reset_tokens" not in job_ids
    assert "purge_old_request_logs" not in job_ids


def test_shows_production_only_jobs_in_production(client, make_user, monkeypatch):
    # Set the env BEFORE login_headers() triggers the first get_settings()
    # call in this test (see the same pattern in TestTriggerBackup below).
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    headers = login_headers(client, make_user, administrator=True)

    response = client.get("/administrator/scheduler/jobs", headers=headers)

    assert response.status_code == 200
    job_ids = {job["id"] for job in response.json()}
    assert "backup_koofr" in job_ids
    assert "notify_upcoming_booking_status" in job_ids
    assert "purge_expired_password_reset_tokens" in job_ids
    assert "purge_old_request_logs" in job_ids
    assert "downsync" not in job_ids


class TestTriggerBackup:
    def test_queues_the_manual_backup_and_answers_202(
        self, client, make_user, monkeypatch, fake_arq_pool
    ):
        # Set the env BEFORE login_headers() triggers the first
        # get_settings() call in this test (login itself doesn't depend on
        # app_environment, but get_settings() is lru_cache'd -- see
        # conftest.py's client fixture docstring).
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        headers = login_headers(client, make_user, administrator=True)

        response = client.post(
            "/administrator/scheduler/backup/trigger", headers=headers
        )

        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == "backup_koofr"
        # Locks in the UtcDatetime contract (Zeitzonen-Konsolidierung,
        # 2026-08-14): must carry a real UTC offset, not an offset-free
        # string, consistent with every other UTC-instant response field.
        assert datetime.fromisoformat(body["queued_at"]).tzinfo is not None
        fake_arq_pool.enqueue_job.assert_awaited_once_with(
            "manual_backup_task", _job_id="backup_koofr"
        )

    def test_returns_409_outside_production_without_queueing(
        self, client, make_user, fake_arq_pool
    ):
        headers = login_headers(client, make_user, administrator=True)

        response = client.post(
            "/administrator/scheduler/backup/trigger", headers=headers
        )

        assert response.status_code == 409
        fake_arq_pool.enqueue_job.assert_not_called()


class TestTriggerDownsync:
    def test_queues_the_manual_downsync_and_answers_202(
        self, client, make_user, fake_arq_pool
    ):
        headers = login_headers(client, make_user, administrator=True)

        response = client.post(
            "/administrator/scheduler/downsync/trigger", headers=headers
        )

        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == "downsync"
        assert datetime.fromisoformat(body["queued_at"]).tzinfo is not None
        fake_arq_pool.enqueue_job.assert_awaited_once_with(
            "manual_downsync_task", _job_id="downsync"
        )

    def test_returns_409_in_production_without_queueing(
        self, client, make_user, monkeypatch, fake_arq_pool
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        headers = login_headers(client, make_user, administrator=True)

        response = client.post(
            "/administrator/scheduler/downsync/trigger", headers=headers
        )

        assert response.status_code == 409
        fake_arq_pool.enqueue_job.assert_not_called()


class TestNPlusOne:
    def test_list_jobs_query_count_does_not_scale_with_job_run_count(
        self, client, make_user, db_session: Session, count_queries
    ):
        """get_latest_run_per_job() is one DISTINCT ON query, not one per
        job -- adding more job_runs rows across every job must not add
        more SQL statements to GET /jobs."""
        headers = login_headers(client, make_user, administrator=True)

        with count_queries() as before_any_runs:
            response_before = client.get(
                "/administrator/scheduler/jobs", headers=headers
            )

        for job_id in (
            "purge_stale_booking_requests",
            "notify_upcoming_booking_status",
            "purge_expired_password_reset_tokens",
            "purge_old_request_logs",
            "backup_koofr",
            "downsync",
        ):
            for offset in range(3):
                started_at = datetime(2026, 9, 1, offset, tzinfo=UTC)
                db_session.add(
                    JobRun(
                        job_id=job_id,
                        status="success",
                        started_at=started_at,
                        finished_at=started_at,
                    )
                )
        db_session.commit()

        with count_queries() as after_many_runs:
            response_after = client.get(
                "/administrator/scheduler/jobs", headers=headers
            )

        assert response_before.status_code == 200
        assert response_after.status_code == 200
        assert after_many_runs.count == before_any_runs.count
