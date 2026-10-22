import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.api.middleware import request_logging
from app.api.middleware.request_logging import RequestLoggingMiddleware
from app.db.models.request_log import RequestLog
from app.services import request_log_service

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from starlette.types import Receive, Scope, Send


def test_writes_a_row_for_a_regular_request(client, db_session: Session):
    response = client.get("/nonexistent-path-for-logging-test")
    assert response.status_code == 404

    row = db_session.execute(
        select(RequestLog).where(
            RequestLog.request_path == "/nonexistent-path-for-logging-test"
        )
    ).scalar_one()
    assert row.request_method == "GET"
    assert row.response_status == 404


def test_skips_the_liveness_check(client, db_session: Session):
    response = client.get("/")
    assert response.status_code == 200

    count = db_session.scalar(
        select(func.count())
        .select_from(RequestLog)
        .where(RequestLog.request_path == "/")
    )
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
        db_session.execute(
            select(RequestLog)
            .where(RequestLog.request_path == "/auth/login")
            .order_by(RequestLog.id.desc())
        )
        .scalars()
        .first()
    )
    assert row is not None
    stored_request = row.request_input
    assert stored_request["password"] == "__removed__"
    stored_response = row.response_content
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
# (a general-purpose hook) -- tested here directly against the middleware
# instead of hunting for/adding an artificial real route.


def _make_skip_header_app() -> Starlette:
    async def _skip_endpoint(_request):
        return JSONResponse({"ok": True}, headers={"X-Skip-Request-Log": "1"})

    app = Starlette(routes=[Route("/skip-me", _skip_endpoint)])
    app.add_middleware(RequestLoggingMiddleware)
    return app


def test_a_failing_log_write_does_not_fail_the_request(
    client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    def _database_unavailable(*_args: object, **_kwargs: object) -> None:
        statement = "INSERT INTO request_logs DEFAULT VALUES"
        raise OperationalError(statement, {}, Exception("database unavailable"))

    monkeypatch.setattr(request_log_service, "record_request", _database_unavailable)

    response = client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 401
    assert "Could not write the request log entry." in caplog.text


def test_only_database_errors_are_swallowed_by_the_log_write(
    client, monkeypatch: pytest.MonkeyPatch
):
    def _programming_error(*_args: object, **_kwargs: object) -> None:
        msg = "not a database problem"
        raise RuntimeError(msg)

    monkeypatch.setattr(request_log_service, "record_request", _programming_error)

    with pytest.raises(RuntimeError, match="not a database problem"):
        client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})


def test_strips_the_skip_header_before_it_reaches_the_client():
    with TestClient(_make_skip_header_app()) as isolated_client:
        response = isolated_client.get("/skip-me")
    assert response.status_code == 200
    assert "x-skip-request-log" not in {key.lower() for key in response.headers}


def test_does_not_write_a_log_row_when_the_skip_header_is_set(db_session: Session):
    with TestClient(_make_skip_header_app()) as isolated_client:
        isolated_client.get("/skip-me")

    count = db_session.scalar(
        select(func.count())
        .select_from(RequestLog)
        .where(RequestLog.request_path == "/skip-me")
    )
    assert count == 0


def test_does_not_buffer_the_response_body_when_the_skip_header_is_set():
    # Regression guard: should_skip() must run BEFORE the body-buffering
    # loop, not after -- otherwise the skip header only ever avoided the
    # DB write, not the expensive in-memory buffering itself. Exercises
    # dispatch() directly (no TestClient/real transport) so the response's
    # own body_iterator can be observed rather than the bytes it yields.
    body_iterator_consumed = False

    async def _body_iterator():
        nonlocal body_iterator_consumed
        body_iterator_consumed = True
        yield b'{"ok": true}'

    response = Response(headers={"X-Skip-Request-Log": "1"})
    response.body_iterator = _body_iterator()  # type: ignore[attr-defined]

    async def _call_next(_request: Request) -> Response:
        return response

    async def _dummy_app(_scope: Scope, _receive: Receive, _send: Send) -> None:
        pass

    async def _empty_receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _run() -> None:
        middleware = RequestLoggingMiddleware(app=_dummy_app)
        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/skip-me",
            "headers": [],
            "query_string": b"",
        }
        request = Request(scope, receive=_empty_receive)
        result = await middleware.dispatch(request, _call_next)
        assert result is response
        assert body_iterator_consumed is False

    asyncio.run(_run())


# --- Payload ceiling, multipart handling and repeated response headers ---


def test_a_payload_at_the_ceiling_is_kept_and_one_byte_more_is_replaced():
    overhead = len(json.dumps({"value": ""}))
    limit = request_logging._MAX_LOGGED_JSON_BYTES
    at_limit = {"value": "x" * (limit - overhead)}
    over_limit = {"value": "x" * (limit - overhead + 1)}

    assert request_logging._bounded_object(at_limit) == at_limit
    assert request_logging._bounded_object(over_limit) == {"truncated": True}
    assert request_logging._bounded(["x" * limit]) == {"truncated": True}
    assert request_logging._bounded(["x"]) == ["x"]
    assert request_logging._bounded(None) is None


def test_the_ceiling_counts_escaped_non_ascii_characters_as_stored():
    limit = request_logging._MAX_LOGGED_JSON_BYTES
    # Each of these characters is stored as a six character escape sequence.
    escaped = {"value": "ä" * (limit // 6)}

    assert request_logging._bounded_object(escaped) == {"truncated": True}


def test_an_oversized_request_body_is_stored_as_a_marker(client, db_session: Session):
    oversized = "x" * (request_logging._MAX_LOGGED_JSON_BYTES + 1)

    client.post("/auth/login", json={"filler": oversized})

    row = db_session.execute(
        select(RequestLog).where(RequestLog.request_path == "/auth/login")
    ).scalar_one()
    assert row.request_input == {"truncated": True}


def test_an_oversized_response_body_is_stored_as_a_marker(db_session: Session):
    oversized = "x" * (request_logging._MAX_LOGGED_JSON_BYTES + 1)

    async def _large_endpoint(_request: Request) -> Response:
        return JSONResponse({"filler": oversized})

    app = Starlette(routes=[Route("/large", _large_endpoint)])
    app.add_middleware(RequestLoggingMiddleware)

    with TestClient(app) as isolated_client:
        response = isolated_client.get("/large")

    assert response.json() == {"filler": oversized}
    row = db_session.execute(
        select(RequestLog).where(RequestLog.request_path == "/large")
    ).scalar_one()
    assert row.response_content == {"truncated": True}


def test_multipart_bodies_are_not_parsed_for_the_log(client, db_session: Session):
    client.post(
        "/auth/login",
        data={"note": "visible in a urlencoded body only"},
        files={"upload": ("notes.txt", b"file content")},
    )

    row = db_session.execute(
        select(RequestLog).where(RequestLog.request_path == "/auth/login")
    ).scalar_one()
    assert row.request_input == {}


def test_repeated_response_headers_survive_the_rebuilt_response():
    async def _two_cookies(_request: Request) -> Response:
        response = JSONResponse({"ok": True})
        response.set_cookie("first", "1")
        response.set_cookie("second", "2")
        return response

    app = Starlette(routes=[Route("/cookies", _two_cookies)])
    app.add_middleware(RequestLoggingMiddleware)

    with (
        patch("app.api.middleware.request_logging._write_log_entry"),
        TestClient(app) as isolated_client,
    ):
        response = isolated_client.get("/cookies")

    assert len(response.headers.get_list("set-cookie")) == 2
    assert response.json() == {"ok": True}
