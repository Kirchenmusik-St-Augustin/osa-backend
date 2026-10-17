import asyncio
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.exception_handlers import _handle_rate_limit_exceeded
from app.core.rate_limit import client_ip
from main import app

_DOCKERFILE = Path(__file__).parents[2] / "Dockerfile"
_VERIFY_EMAIL_PATH = "/auth/verify-email"  # limited to 5 requests per hour
_VERIFY_EMAIL_PAYLOAD = {"token": "not-a-real-token"}


def _request_from(client: tuple[str, int] | None) -> Request:
    return Request({"type": "http", "headers": [], "client": client})


def test_client_ip_returns_the_resolved_peer_address():
    assert client_ip(_request_from(("203.0.113.9", 4711))) == "203.0.113.9"


def test_client_ip_without_a_client_falls_back_to_unknown():
    assert client_ip(_request_from(None)) == "unknown"


def test_rate_limit_buckets_are_kept_per_client_address():
    headers = {"Origin": os.environ["CORS_ORIGINS"]}
    first = TestClient(app, client=("198.51.100.1", 50000), headers=headers)
    second = TestClient(app, client=("198.51.100.2", 50000), headers=headers)

    for _ in range(5):
        assert (
            first.post(_VERIFY_EMAIL_PATH, json=_VERIFY_EMAIL_PAYLOAD).status_code
            != 429
        )
    exhausted = first.post(_VERIFY_EMAIL_PATH, json=_VERIFY_EMAIL_PAYLOAD)
    other_visitor = second.post(_VERIFY_EMAIL_PATH, json=_VERIFY_EMAIL_PAYLOAD)

    assert exhausted.status_code == 429
    assert other_visitor.status_code != 429


def test_exceeded_limit_answers_with_a_german_detail_and_retry_after():
    headers = {"Origin": os.environ["CORS_ORIGINS"]}
    visitor = TestClient(app, client=("198.51.100.3", 50000), headers=headers)
    for _ in range(5):
        visitor.post(_VERIFY_EMAIL_PATH, json=_VERIFY_EMAIL_PAYLOAD)

    response = visitor.post(_VERIFY_EMAIL_PATH, json=_VERIFY_EMAIL_PAYLOAD)

    assert response.status_code == 429
    assert response.json() == {
        "detail": "Zu viele Anfragen. Bitte später erneut versuchen."
    }
    assert 1 <= int(response.headers["retry-after"]) <= 3600


def test_exceeded_limit_without_a_recorded_window_has_no_retry_after():
    request = _request_from(("203.0.113.9", 4711))

    response = asyncio.run(_handle_rate_limit_exceeded(request, Exception()))

    assert response.status_code == 429
    assert "retry-after" not in response.headers


def test_production_command_trusts_the_forwarded_address_of_the_proxy():
    """Behind Caddy every connection comes from the same internal address, so
    without this flag all visitors would share one rate-limit bucket."""
    command = re.search(
        r'^CMD \["gunicorn".*?\]$', _DOCKERFILE.read_text(), re.DOTALL | re.MULTILINE
    )

    assert command is not None
    assert '"--forwarded-allow-ips", "*"' in command.group(0)
