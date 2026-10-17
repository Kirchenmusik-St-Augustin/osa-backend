"""Global FastAPI exception handlers for the shared service-layer error
hierarchy defined in app.services.errors, registered once from main.py.
No router needs a try/except for NotFoundError/DomainValidationError/
PlainError anymore -- see each class's docstring for the response shape
it renders.

Each handler below is typed against the base `Exception` Starlette's own
`ExceptionHandler` protocol expects (a narrower parameter type would be
contravariantly unsound, and main.py's own handlers dodge this only
because main.py sits outside pyright's `include` path) and casts back to
the real, narrower type -- Starlette only ever dispatches a registered
handler for its exact registered exception class or a subclass, so the
cast merely documents a guarantee the framework itself already enforces,
not an assumption of ours."""

import time
from math import ceil
from typing import cast

from fastapi import FastAPI, status
from limits import RateLimitItem
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.error_responses import field_errors_to_detail
from app.core.rate_limit import limiter
from app.services.errors import DomainValidationError, NotFoundError, PlainError

_NOT_FOUND_DETAIL = "Nicht gefunden."
_RATE_LIMITED_DETAIL = "Zu viele Anfragen. Bitte später erneut versuchen."


async def _handle_not_found(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": _NOT_FOUND_DETAIL}
    )


async def _handle_domain_validation_error(
    _request: Request, exc: Exception
) -> JSONResponse:
    domain_exc = cast("DomainValidationError", exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": field_errors_to_detail(domain_exc.errors)},
    )


async def _handle_plain_error(_request: Request, exc: Exception) -> JSONResponse:
    plain_exc = cast("PlainError", exc)
    return JSONResponse(
        status_code=plain_exc.status_code, content={"detail": plain_exc.detail}
    )


def _seconds_until_reset(request: Request) -> int | None:
    """Seconds until the window of the limit that was just hit has room again,
    or None when slowapi recorded no limit for this request."""
    current_limit = cast(
        "tuple[RateLimitItem, list[str]] | None",
        getattr(request.state, "view_rate_limit", None),
    )
    if current_limit is None:
        return None
    item, scope_key = current_limit
    reset_at, _remaining = limiter.limiter.get_window_stats(item, *scope_key)
    return max(1, ceil(reset_at - time.time()))


async def _handle_rate_limit_exceeded(
    request: Request, _exc: Exception
) -> JSONResponse:
    """Same response shape as every other error (`detail`, German text), so
    the frontend shows it instead of its generic error, plus the standard
    Retry-After header."""
    retry_after = _seconds_until_reset(request)
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": _RATE_LIMITED_DETAIL},
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _handle_not_found)
    app.add_exception_handler(DomainValidationError, _handle_domain_validation_error)
    app.add_exception_handler(PlainError, _handle_plain_error)
    app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)
