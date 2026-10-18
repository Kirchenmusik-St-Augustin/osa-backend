import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Imported for its side effect: registers every model with Base.metadata.
from app.api.exception_handlers import register_exception_handlers
from app.api.middleware.body_limit import MaxBodySizeMiddleware
from app.api.middleware.request_logging import RequestLoggingMiddleware
from app.api.router import api_router
from app.api.router_includes.go import go_router
from app.api.system import system_router
from app.core.arq_pool import close_arq_pool
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.core.rate_limit import limiter

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    logger.info(
        "*** osa-backend starting - environment: %s ***", settings.app_environment
    )
    yield
    await close_arq_pool()
    logger.info("osa-backend shutdown complete.")


def _docs_urls(environment: str | None) -> tuple[str | None, str | None, str | None]:
    """Paths of the interactive documentation (Swagger UI, ReDoc) and of the
    OpenAPI document. They list every route and schema to anyone who asks, so
    they exist outside production only."""
    if environment == "production":
        return None, None, None
    return "/docs", "/redoc", "/openapi.json"


_DOCS_URL, _REDOC_URL, _OPENAPI_URL = _docs_urls(settings.app_environment)

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
    docs_url=_DOCS_URL,
    redoc_url=_REDOC_URL,
    openapi_url=_OPENAPI_URL,
)


register_exception_handlers(app)

app.state.limiter = limiter

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
# the outermost layer -- it sees the actual final response, not an
# intermediate one.
app.add_middleware(RequestLoggingMiddleware)
# Registered last, i.e. the outermost layer: an oversized body is rejected
# before the request logger or any route buffers it in memory.
app.add_middleware(
    MaxBodySizeMiddleware, max_body_bytes=settings.max_request_body_bytes
)

app.include_router(system_router)  # root-level health check, no prefix
app.include_router(api_router)  # every domain router, see app/api/router.py
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
