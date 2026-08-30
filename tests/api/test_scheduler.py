from datetime import datetime
from unittest.mock import patch

from app.services.backup_service import BackupError


def _auth_headers(client, make_user, *, administrator: bool = False) -> dict[str, str]:
    user = make_user(password="correct-password", administrator=administrator)
    response = client.post(
        "/auth/login", data={"username": user.email, "password": "correct-password"}
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestPermissionGuard:
    def test_list_jobs_requires_authentication(self, client):
        response = client.get("/administrator/scheduler/jobs")
        assert response.status_code == 401

    def test_list_jobs_rejects_non_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.get("/administrator/scheduler/jobs", headers=headers)
        assert response.status_code == 403

    def test_list_jobs_allows_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)
        response = client.get("/administrator/scheduler/jobs", headers=headers)
        assert response.status_code == 200

    def test_trigger_backup_requires_authentication(self, client):
        response = client.post("/administrator/scheduler/backup/trigger")
        assert response.status_code == 401

    def test_trigger_backup_rejects_non_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/administrator/scheduler/backup/trigger", headers=headers
        )
        assert response.status_code == 403

    def test_trigger_downsync_requires_authentication(self, client):
        response = client.post("/administrator/scheduler/downsync/trigger")
        assert response.status_code == 401

    def test_trigger_downsync_rejects_non_administrator(self, client, make_user):
        headers = _auth_headers(client, make_user)
        response = client.post(
            "/administrator/scheduler/downsync/trigger", headers=headers
        )
        assert response.status_code == 403


def test_returns_registered_jobs_with_expected_shape(client, make_user):
    # purge_stale_booking_requests is active in every environment, so this
    # is always non-empty regardless of APP_ENVIRONMENT.
    headers = _auth_headers(client, make_user, administrator=True)

    response = client.get("/administrator/scheduler/jobs", headers=headers)

    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) >= 1
    for job in jobs:
        assert set(job.keys()) == {"id", "name", "trigger", "next_run", "description"}


def test_hides_production_only_jobs_outside_production(client, make_user):
    headers = _auth_headers(client, make_user, administrator=True)

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
    # Set the env BEFORE _auth_headers() triggers the first get_settings()
    # call in this test (see the same pattern in TestTriggerBackup below).
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    headers = _auth_headers(client, make_user, administrator=True)

    response = client.get("/administrator/scheduler/jobs", headers=headers)

    assert response.status_code == 200
    job_ids = {job["id"] for job in response.json()}
    assert "backup_koofr" in job_ids
    assert "notify_upcoming_booking_status" in job_ids
    assert "purge_expired_password_reset_tokens" in job_ids
    assert "purge_old_request_logs" in job_ids
    assert "downsync" not in job_ids


class TestTriggerBackup:
    def test_returns_201_with_backup_name_and_triggered_at(
        self, client, make_user, monkeypatch
    ):
        # Set the env BEFORE _auth_headers() triggers the first
        # get_settings() call in this test (login itself doesn't depend on
        # app_environment, but get_settings() is lru_cache'd -- see
        # conftest.py's client fixture docstring).
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        headers = _auth_headers(client, make_user, administrator=True)

        # Patched at the router's import site (app.api.router_includes.scheduler),
        # not app.services.backup_service -- `from ... import run_backup` copies
        # the name into the router module's own namespace.
        with patch(
            "app.api.router_includes.scheduler.run_backup",
            return_value="production-2026-08-13_12-00-00-manual.tar.gz",
        ) as mock_run_backup:
            response = client.post(
                "/administrator/scheduler/backup/trigger", headers=headers
            )

        assert response.status_code == 201
        body = response.json()
        assert body["backup_name"] == "production-2026-08-13_12-00-00-manual.tar.gz"
        # Locks in the UtcDatetime contract (Zeitzonen-Konsolidierung,
        # 2026-08-14): must carry a real UTC offset, not an offset-free
        # string, consistent with every other UTC-instant response field.
        triggered_at = datetime.fromisoformat(body["triggered_at"])
        assert triggered_at.tzinfo is not None
        mock_run_backup.assert_called_once_with(manual=True)

    def test_returns_500_with_detail_when_backup_fails(
        self, client, make_user, monkeypatch
    ):
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        headers = _auth_headers(client, make_user, administrator=True)

        with patch(
            "app.api.router_includes.scheduler.run_backup",
            side_effect=BackupError("Koofr upload failed"),
        ):
            response = client.post(
                "/administrator/scheduler/backup/trigger", headers=headers
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Koofr upload failed"

    def test_returns_409_outside_production_without_running_backup(
        self, client, make_user
    ):
        headers = _auth_headers(client, make_user, administrator=True)

        def unexpected_run_backup(**_kwargs: object) -> str:
            msg = "must never run a backup once blocked by the production gate"
            raise AssertionError(msg)

        with patch(
            "app.api.router_includes.scheduler.run_backup",
            side_effect=unexpected_run_backup,
        ):
            response = client.post(
                "/administrator/scheduler/backup/trigger", headers=headers
            )

        assert response.status_code == 409


class TestTriggerDownsync:
    def test_returns_201_with_restored_backup_and_triggered_at(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        with (
            patch(
                "app.api.router_includes.scheduler.list_backups",
                return_value=[
                    "production-2024-01-01_00-00-00.tar.gz",
                    "production-2024-06-01_00-00-00.tar.gz",
                ],
            ) as mock_list_backups,
            patch(
                "app.api.router_includes.scheduler.run_restore",
                return_value="production-2024-06-01_00-00-00.tar.gz",
            ) as mock_run_restore,
        ):
            response = client.post(
                "/administrator/scheduler/downsync/trigger", headers=headers
            )

        assert response.status_code == 201
        body = response.json()
        assert body["restored_backup"] == "production-2024-06-01_00-00-00.tar.gz"
        triggered_at = datetime.fromisoformat(body["triggered_at"])
        assert triggered_at.tzinfo is not None
        mock_list_backups.assert_called_once_with(stage="production")
        mock_run_restore.assert_called_once_with(
            backup_name="production-2024-06-01_00-00-00.tar.gz"
        )

    def test_returns_409_in_production_without_listing_backups(
        self, client, make_user, monkeypatch
    ):
        # Set the env BEFORE _auth_headers() triggers the first
        # get_settings() call in this test (login itself doesn't depend on
        # app_environment, but get_settings() is lru_cache'd -- see
        # conftest.py's client fixture docstring).
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        headers = _auth_headers(client, make_user, administrator=True)

        def unexpected_list_backups(**_kwargs: object) -> list[str]:
            msg = "must never list backups once blocked by the production gate"
            raise AssertionError(msg)

        with patch(
            "app.api.router_includes.scheduler.list_backups",
            side_effect=unexpected_list_backups,
        ):
            response = client.post(
                "/administrator/scheduler/downsync/trigger", headers=headers
            )

        assert response.status_code == 409

    def test_returns_404_when_no_production_backup_exists(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        with patch("app.api.router_includes.scheduler.list_backups", return_value=[]):
            response = client.post(
                "/administrator/scheduler/downsync/trigger", headers=headers
            )

        assert response.status_code == 404

    def test_returns_500_with_detail_when_restore_fails(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        with (
            patch(
                "app.api.router_includes.scheduler.list_backups",
                return_value=["production-2024-01-01_00-00-00.tar.gz"],
            ),
            patch(
                "app.api.router_includes.scheduler.run_restore",
                side_effect=BackupError("Koofr download failed"),
            ),
        ):
            response = client.post(
                "/administrator/scheduler/downsync/trigger", headers=headers
            )

        assert response.status_code == 500
        assert response.json()["detail"] == "Koofr download failed"
