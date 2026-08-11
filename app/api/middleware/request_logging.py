"""Global request/response audit logging (Schritt 9) -- runs outside any
request's own Depends() chain (ASGI middleware, not a route function), so it
opens its own short-lived SessionLocal() per request, the same documented
exception as app/core/mailer.py/app/services/booking_jobs.py (see
pyproject.toml's per-file-ignores for TID251)."""

import json
import resource
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.deps import try_decode_token
from app.db.database import SessionLocal
from app.db.models.user import User
from app.services import request_log_service

_SKIP_LOG_HEADER = "x-skip-request-log"


async def _extract_request_input(request: Request) -> dict[str, object]:
    """Best-effort read of the request body as a dict -- mirrors Legacy's
    `$request->all()`, which handles both JSON bodies and form-encoded
    bodies (our own login endpoint uses OAuth2PasswordRequestForm, i.e.
    x-www-form-urlencoded, not JSON)."""
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    if not body:
        return {}
    if "application/json" in content_type:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    if (
        "application/x-www-form-urlencoded" in content_type
        or "multipart/form-data" in content_type
    ):
        form = await request.form()
        return {
            key: value for key, value in form.multi_items() if isinstance(value, str)
        }
    return {}


def _try_parse_json(body: bytes) -> object:
    # Mirrors Legacy's `json_decode($response->content())` -- returns None
    # for any non-JSON (or empty) response body, same as PHP's json_decode.
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _forwarded_ips(request: Request) -> list[str]:
    # Mirrors Legacy's `$request->ips()` (full X-Forwarded-For chain, most
    # recent proxy last) -- Starlette has no built-in equivalent, so this
    # is read directly off the header, falling back to the direct peer.
    header = request.headers.get("x-forwarded-for")
    if not header:
        return [request.client.host] if request.client else []
    return [part.strip() for part in header.split(",") if part.strip()]


def _memory_usage_bytes() -> int:
    # Approximates Legacy's `memory_get_usage()` (live PHP heap) with the
    # process's peak resident set size -- a different metric, but the field
    # is purely informational (no business logic reads it), and Linux
    # containers report ru_maxrss in KiB.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def _write_log_entry(
    *,
    client_ip: str,
    client_ips: list[str],
    auth_header: str | None,
    request_method: str,
    request_path: str,
    request_input: dict[str, object],
    response_status: int,
    response_content: object,
    memory_usage: int,
    user_agent_string: str | None,
) -> None:
    """The one synchronous, DB-touching unit of work per request -- always
    invoked through `run_in_threadpool()` by the middleware below so it
    never blocks the event loop (CLAUDE.md: async handlers must never
    block; a Starlette middleware, unlike a sync FastAPI route function,
    does NOT get that offload automatically)."""
    db: Session = SessionLocal()
    try:
        user_id = _resolve_user_id(db, auth_header)
        request_log_service.record_request(
            db,
            client_ip=client_ip,
            client_ips=client_ips,
            user_id=user_id,
            user_agent_string=user_agent_string,
            request_method=request_method,
            request_path=request_path,
            request_input=request_input,
            response_status=response_status,
            response_content=response_content,
            memory_usage=memory_usage,
        )
    finally:
        db.close()


def _resolve_user_id(db: Session, auth_header: str | None) -> int | None:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    email = try_decode_token(auth_header[len("bearer ") :])
    if email is None:
        return None
    return db.execute(select(User.id).where(User.email == email)).scalar_one_or_none()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """1:1 port of Legacy's `RequestLogging` middleware (`terminate()` hook,
    global on the `web` group -- every request gets logged, not just
    Administrator-domain ones). See app.services.request_log_service for
    the exclusion rules and redaction logic."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_input = await _extract_request_input(request)
        response = await call_next(request)

        response_body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            response_body += chunk

        skip_header_present = _SKIP_LOG_HEADER in response.headers
        rebuilt = Response(
            content=response_body,
            status_code=response.status_code,
            headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() != _SKIP_LOG_HEADER
            },
            media_type=response.media_type,
            background=response.background,
        )

        if request_log_service.should_skip(
            request.url.path, skip_header_present=skip_header_present
        ):
            return rebuilt

        client_ips = _forwarded_ips(request)
        await run_in_threadpool(
            _write_log_entry,
            client_ip=client_ips[0] if client_ips else "",
            client_ips=client_ips,
            auth_header=request.headers.get("authorization"),
            request_method=request.method,
            request_path=request.url.path,
            request_input=request_input,
            response_status=response.status_code,
            response_content=_try_parse_json(response_body),
            memory_usage=_memory_usage_bytes(),
            user_agent_string=request.headers.get("user-agent"),
        )
        return rebuilt
