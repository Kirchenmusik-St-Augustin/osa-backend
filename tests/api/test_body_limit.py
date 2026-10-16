import asyncio
from typing import TYPE_CHECKING

from app.api.middleware.body_limit import MaxBodySizeMiddleware
from app.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.types import Message, Receive, Scope, Send


def _limit() -> int:
    return get_settings().max_request_body_bytes


def test_body_with_oversized_content_length_is_rejected(client):
    response = client.post(
        "/auth/login",
        content=b"x" * (_limit() + 1),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Die Anfrage ist zu groß."}


def test_chunked_body_over_the_limit_is_rejected_without_content_length(client):
    def chunks() -> Iterator[bytes]:
        for _ in range(3):
            yield b"x" * (_limit() // 2 + 1)

    response = client.post(
        "/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413


def test_body_within_the_limit_reaches_the_route(client):
    response = client.post(
        "/auth/login", data={"username": "nobody@example.test", "password": "x"}
    )

    assert response.status_code == 401


def _drive(
    app_under_test: MaxBodySizeMiddleware, scope: Scope, incoming: list[Message]
) -> list[Message]:
    """Run one request through the middleware and return what it sent."""
    sent: list[Message] = []
    pending = iter(incoming)

    async def receive() -> Message:
        return next(pending)

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app_under_test(scope, receive, send))
    return sent


def _http_scope(content_length: bytes | None) -> Scope:
    headers = [] if content_length is None else [(b"content-length", content_length)]
    return {"type": "http", "method": "POST", "path": "/", "headers": headers}


async def _answer_ok_after_reading(receive: Receive, send: Send) -> None:
    while (await receive()).get("more_body", False):
        pass
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def test_non_http_scopes_are_passed_through_untouched():
    seen: list[tuple[Scope, Receive]] = []

    async def inner(scope: Scope, receive: Receive, _send: Send) -> None:
        seen.append((scope, receive))

    middleware = MaxBodySizeMiddleware(inner, max_body_bytes=1)
    scope: Scope = {"type": "lifespan"}

    async def receive() -> Message:
        return {"type": "lifespan.startup"}

    async def send(_message: Message) -> None:
        return None

    asyncio.run(middleware(scope, receive, send))

    assert seen == [(scope, receive)]


def test_non_numeric_content_length_falls_back_to_counting_received_bytes():
    async def inner(_scope: Scope, receive: Receive, send: Send) -> None:
        await _answer_ok_after_reading(receive, send)

    middleware = MaxBodySizeMiddleware(inner, max_body_bytes=4)

    within = _drive(
        middleware,
        _http_scope(b"abc"),
        [{"type": "http.request", "body": b"1234", "more_body": False}],
    )
    over = _drive(
        middleware,
        _http_scope(b"abc"),
        [{"type": "http.request", "body": b"12345", "more_body": False}],
    )

    assert within[0]["status"] == 200
    assert over[0]["status"] == 413


def test_disconnect_messages_do_not_count_towards_the_limit():
    async def inner(_scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = MaxBodySizeMiddleware(inner, max_body_bytes=1)

    sent = _drive(middleware, _http_scope(None), [{"type": "http.disconnect"}])

    assert sent[0]["status"] == 204


def test_overrun_after_the_response_started_sends_no_second_response():
    async def inner(_scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    middleware = MaxBodySizeMiddleware(inner, max_body_bytes=2)

    sent = _drive(
        middleware,
        _http_scope(None),
        [{"type": "http.request", "body": b"123", "more_body": False}],
    )

    assert [message["type"] for message in sent] == ["http.response.start"]
    assert sent[0]["status"] == 200


def test_declared_length_exactly_at_the_limit_is_accepted():
    async def inner(_scope: Scope, receive: Receive, send: Send) -> None:
        await _answer_ok_after_reading(receive, send)

    middleware = MaxBodySizeMiddleware(inner, max_body_bytes=4)

    at_limit = _drive(
        middleware,
        _http_scope(b"4"),
        [{"type": "http.request", "body": b"1234", "more_body": False}],
    )
    above_limit = _drive(middleware, _http_scope(b"5"), [])

    assert at_limit[0]["status"] == 200
    assert above_limit[0]["status"] == 413
