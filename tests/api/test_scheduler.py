from app.core.scheduler import stop_scheduler


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
