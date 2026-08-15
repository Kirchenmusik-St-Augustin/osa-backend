from datetime import datetime
from unittest.mock import patch

from app.core.scheduler import stop_scheduler
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


def test_returns_registered_jobs_with_expected_shape(client, make_user):
    # The client fixture's lifespan startup already ran start_scheduler()
    # under APP_ENVIRONMENT=test, so at least the always-on job is present.
    headers = _auth_headers(client, make_user, administrator=True)

    response = client.get("/administrator/scheduler/jobs", headers=headers)

    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) >= 1
    for job in jobs:
        assert set(job.keys()) == {"id", "name", "trigger", "next_run", "description"}


def test_returns_empty_list_when_scheduler_stopped(client, make_user):
    stop_scheduler()
    headers = _auth_headers(client, make_user, administrator=True)

    response = client.get("/administrator/scheduler/jobs", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


class TestTriggerBackup:
    def test_returns_201_with_backup_name_and_triggered_at(self, client, make_user):
        headers = _auth_headers(client, make_user, administrator=True)

        # Patched at the router's import site (app.api.router_includes.scheduler),
        # not app.services.backup_service -- `from ... import run_backup` copies
        # the name into the router module's own namespace.
        with patch(
            "app.api.router_includes.scheduler.run_backup",
            return_value="test-2026-08-13_12-00-00-manual.tar.gz",
        ) as mock_run_backup:
            response = client.post(
                "/administrator/scheduler/backup/trigger", headers=headers
            )

        assert response.status_code == 201
        body = response.json()
        assert body["backup_name"] == "test-2026-08-13_12-00-00-manual.tar.gz"
        # Locks in the UtcDatetime contract (Zeitzonen-Konsolidierung,
        # 2026-08-14): must carry a real UTC offset, not an offset-free
        # string, consistent with every other UTC-instant response field.
        triggered_at = datetime.fromisoformat(body["triggered_at"])
        assert triggered_at.tzinfo is not None
        mock_run_backup.assert_called_once_with(manual=True)

    def test_returns_500_with_detail_when_backup_fails(self, client, make_user):
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
