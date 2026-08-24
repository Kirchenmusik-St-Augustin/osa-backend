import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

import app.db.base
from app.api.middleware.request_logging import RequestLoggingMiddleware
from app.api.router import api_router
from app.api.router_includes.go import go_router
from app.api.system import system_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.core.rate_limit import limiter
from app.core.scheduler import start_scheduler, stop_scheduler

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info(
        "*** osa-backend starting - environment: %s ***", settings.app_environment
    )
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("osa-backend shutdown complete.")


app = FastAPI(
    title="OSA API",
    description="Backend for the Orchester-Einteilung scheduling system.",
    version="0.1.0",
    lifespan=lifespan,
    # Caddy's `handle_path /api/*` strips the "/api" prefix before this
    # container ever sees a request (see the dev Caddyfile), so every route
    # below is registered WITHOUT an "/api" prefix. root_path only tells
    # FastAPI it is externally reachable under "/api", for correct
    # OpenAPI/docs URL generation -- see FastAPI's "Behind a Proxy" docs.
    # Do NOT also add prefix="/api" to api_router below -- that would
    # double-prefix and 404 everything through Caddy.
    root_path="/api",
)


async def _validation_error_handler(
    _request: Request, exc: ValidationError
) -> JSONResponse:
    """Give a bare pydantic ValidationError (raised in service code, not
    FastAPI's request-parsing RequestValidationError) the same
    {"detail": [...]} shape FastAPI's built-in handler already uses."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder({"detail": exc.errors()}),
    )


# Pydantic's own error catalog is English-only -- the project requires
# fully German validation text for the Auth-domain forms this slice introduces
# (User decision 2026-07-28, see the Schritt-2 plan). Only translates the
# error `type`s Pydantic's built-in validation can actually produce; custom
# field_validators (added in later Auth-domain schemas) already raise their
# own German ValueError messages, which Pydantic wraps as "Value error, {msg}"
# -- those pass through untouched below rather than being overwritten.
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


def _translate_validation_error(error: dict[str, object]) -> str:
    error_type = str(error.get("type", ""))
    raw_msg = str(error.get("msg", ""))
    if error_type == "value_error" and raw_msg.startswith("Value error, "):
        return raw_msg.removeprefix("Value error, ")
    return _GERMAN_VALIDATION_MESSAGES.get(error_type, raw_msg)


async def _request_validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "loc": error.get("loc", []),
            "msg": _translate_validation_error(error),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder({"detail": errors}),
    )


async def _unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Safety net: logs the full traceback server-side, never leaks it."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Ein unerwarteter Fehler ist aufgetreten."},
    )


app.add_exception_handler(ValidationError, _validation_error_handler)
app.add_exception_handler(RequestValidationError, _request_validation_error_handler)
app.add_exception_handler(Exception, _unhandled_exception_handler)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Same-origin in the default deployment -- never triggers today. Kept
# real and typed so a future domain split is a pure config change
# (CORS_ORIGINS), never a code change.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
# Registered AFTER CORSMiddleware so add_middleware's LIFO stacking makes it
# the outermost layer -- it sees the actual final response (Admin-/Audit-
# Viewer, Schritt 9), not an intermediate one.
app.add_middleware(RequestLoggingMiddleware)

app.include_router(system_router)  # root-level health check, no prefix
app.include_router(api_router)  # wiring point for future domain routers, empty today
# Public, unauthenticated redirect service for the dedicated go.-subdomain
# (see app.api.router_includes.go's docstring). Mounted directly on `app`
# under its own "/go" prefix -- NOT nested under api_router, since it has
# no relation to "/api" at all. This prefix is unreachable through the
# main app domain's Caddy route (which only forwards "/api/*" to this
# container); it is only reached via the go.-domain's own Caddy vhost,
# which rewrites every request to prepend "/go" before proxying to this
# same backend port -- the mirror image of the "/api" prefix-stripping
# already used for the main domain. Same process, same port, no second
# container (consistent with the in-process scheduler precedent).
app.include_router(go_router, prefix="/go")
