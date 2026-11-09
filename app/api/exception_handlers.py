"""Global FastAPI exception handlers for the shared service-layer error
hierarchy defined in app.services.errors, registered once from main.py.
No router needs a try/except for NotFoundError/DomainValidationError/
PlainError anymore -- see each class's docstring for the response shape
it renders.

Each handler below is typed against the base `Exception` Starlette's own
`ExceptionHandler` protocol expects (a narrower parameter type would be
contravariantly unsound) and casts back to the real, narrower type --
Starlette only ever dispatches a registered handler for its exact
registered exception class or a subclass, so the cast merely documents a
guarantee the framework itself already enforces, not an assumption of
ours."""

import logging
import time
from math import ceil
from typing import cast

from fastapi import FastAPI, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from limits import RateLimitItem
from pydantic import ValidationError
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.error_responses import field_errors_to_detail
from app.core.rate_limit import limiter
from app.services.errors import DomainValidationError, NotFoundError, PlainError

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "Nicht gefunden."
_RATE_LIMITED_DETAIL = "Zu viele Anfragen. Bitte später erneut versuchen."

# Pydantic's own error catalog is English-only -- the project requires
# fully German validation text for its forms. Only translates the error
# `type`s Pydantic's built-in validation can actually produce; custom
# field_validators already raise their own German ValueError messages, which
# Pydantic wraps as "Value error, {msg}" -- those pass through untouched
# below rather than being overwritten.
_GERMAN_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "Dieses Feld ist erforderlich.",
    "string_type": "Dieser Wert muss eine Zeichenkette sein.",
    "int_type": "Dieser Wert muss eine Ganzzahl sein.",
    "float_type": "Dieser Wert muss eine Zahl sein.",
    "bool_type": "Dieser Wert muss ein Wahrheitswert sein.",
    "string_too_short": "Dieser Wert ist zu kurz.",
    "string_too_long": "Dieser Wert ist zu lang.",
    "extra_forbidden": "Unbekanntes Feld.",
}


def translate_validation_error(error: dict[str, object]) -> str:
    error_type = str(error.get("type", ""))
    raw_msg = str(error.get("msg", ""))
    if error_type == "value_error" and raw_msg.startswith("Value error, "):
        return raw_msg.removeprefix("Value error, ")
    return _GERMAN_VALIDATION_MESSAGES.get(error_type, raw_msg)


async def _handle_validation_error(_request: Request, exc: Exception) -> JSONResponse:
    """Request bodies (FastAPI's RequestValidationError) and models validated
    inside service code (a bare pydantic ValidationError) get one shape:
    location, German message and error type. The offending input is left
    out: for a model built from database rows it would be the row's data,
    for a login form the password."""
    validation_exc = cast("ValidationError | RequestValidationError", exc)
    errors = [
        {
            "loc": error.get("loc", []),
            "msg": translate_validation_error(dict(error)),
            "type": error.get("type", ""),
        }
        for error in validation_exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder({"detail": errors}),
    )


async def _handle_integrity_error(_request: Request, exc: Exception) -> JSONResponse:
    """Safety net for FK/UNIQUE/CHECK constraint violations that reach the
    database without already having been rejected by a service-layer check
    (e.g. a race between a dependency check and the delete/insert
    statement) -- logs the actual constraint detail server-side, never
    leaks it verbatim to the client."""
    logger.warning("IntegrityError: %s", cast("IntegrityError", exc))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": (
                "Die Änderung verletzt eine Datenbank-Constraint, z. B. "
                "eine Referenz auf einen nicht existierenden oder noch "
                "verwendeten Datensatz."
            )
        },
    )


async def _handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    """Safety net: logs the full traceback server-side, never leaks it."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Ein unerwarteter Fehler ist aufgetreten."},
    )


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
    app.add_exception_handler(ValidationError, _handle_validation_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(IntegrityError, _handle_integrity_error)
    app.add_exception_handler(NotFoundError, _handle_not_found)
    app.add_exception_handler(DomainValidationError, _handle_domain_validation_error)
    app.add_exception_handler(PlainError, _handle_plain_error)
    app.add_exception_handler(RateLimitExceeded, _handle_rate_limit_exceeded)
    app.add_exception_handler(Exception, _handle_unexpected_error)
