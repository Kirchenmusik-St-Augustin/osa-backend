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

from typing import cast

from fastapi import FastAPI, status
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.error_responses import field_errors_to_detail
from app.services.errors import DomainValidationError, NotFoundError, PlainError

_NOT_FOUND_DETAIL = "Nicht gefunden."


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


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _handle_not_found)
    app.add_exception_handler(DomainValidationError, _handle_domain_validation_error)
    app.add_exception_handler(PlainError, _handle_plain_error)
