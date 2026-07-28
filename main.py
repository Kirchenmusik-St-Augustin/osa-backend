import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.router import api_router
from app.api.system import system_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
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
app.add_exception_handler(Exception, _unhandled_exception_handler)

# Same-origin in the default deployment (see CLAUDE.md) -- never triggers
# today. Kept real and typed so a future domain split is a pure config
# change (CORS_ORIGINS), never a code change.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.include_router(system_router)  # root-level health check, no prefix
app.include_router(api_router)  # wiring point for future domain routers, empty today
