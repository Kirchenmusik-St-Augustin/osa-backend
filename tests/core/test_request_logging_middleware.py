import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.api.middleware.request_logging import RequestLoggingMiddleware
from app.db.models.request_log import RequestLog


@pytest.fixture(autouse=True)
def _clear_request_logs(db_session: Session):
    yield
    db_session.query(RequestLog).delete()
    db_session.commit()


def test_writes_a_row_for_a_regular_request(client, db_session: Session):
    response = client.get("/nonexistent-path-for-logging-test")
    assert response.status_code == 404

    row = (
        db_session.query(RequestLog)
        .filter(RequestLog.request_path == "/nonexistent-path-for-logging-test")
        .one()
    )
    assert row.request_method == "GET"
    assert row.response_status == 404


def test_skips_the_liveness_check(client, db_session: Session):
    response = client.get("/")
    assert response.status_code == 200

    count = db_session.query(RequestLog).filter(RequestLog.request_path == "/").count()
    assert count == 0


def test_redacts_password_and_access_token_end_to_end(
    client, make_user, db_session: Session
):
    user = make_user(password="correct-horse-battery-staple")

    response = client.post(
        "/auth/login",
        data={"username": user.email, "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()  # the real, unredacted client response

    row = (
        db_session.query(RequestLog)
        .filter(RequestLog.request_path == "/auth/login")
        .order_by(RequestLog.id.desc())
        .first()
    )
    assert row is not None
    stored_request = json.loads(row.request_input)
    assert stored_request["password"] == "__removed__"
    stored_response = json.loads(row.response_content)
    assert stored_response["access_token"] == "__removed__"


def test_uses_run_in_threadpool_so_the_event_loop_is_never_blocked(client):
    # Async code must never block the event loop. A Starlette middleware
    # doesn't get FastAPI's automatic sync-handler threadpool offload, so
    # this must be explicit -- regression guard for that.
    with patch(
        "app.api.middleware.request_logging.run_in_threadpool",
        new_callable=AsyncMock,
    ) as spy:
        client.get("/some/path/for/threadpool/spy")
    spy.assert_awaited_once()


# --- Isolated middleware tests (minimal ad-hoc app, not the real FastAPI app) ---
# The skip-header escape hatch has no real caller anywhere in the app today
# (ported from Legacy as a general-purpose future hook, same as Legacy's own
# unused-by-any-current-route header) -- tested here directly against the
# middleware instead of hunting for/adding an artificial real route.


def _make_skip_header_app() -> Starlette:
    async def _skip_endpoint(_request):
        return JSONResponse({"ok": True}, headers={"X-Skip-Request-Log": "1"})

    app = Starlette(routes=[Route("/skip-me", _skip_endpoint)])
    app.add_middleware(RequestLoggingMiddleware)
    return app


def test_strips_the_skip_header_before_it_reaches_the_client():
    with TestClient(_make_skip_header_app()) as isolated_client:
        response = isolated_client.get("/skip-me")
    assert response.status_code == 200
    assert "x-skip-request-log" not in {key.lower() for key in response.headers}


def test_does_not_write_a_log_row_when_the_skip_header_is_set(db_session: Session):
    with TestClient(_make_skip_header_app()) as isolated_client:
        isolated_client.get("/skip-me")

    count = (
        db_session.query(RequestLog)
        .filter(RequestLog.request_path == "/skip-me")
        .count()
    )
    assert count == 0
