"""Lazily-created singleton ArqRedis connection pool, used to enqueue
background jobs onto the dedicated arq worker container (see
app/worker/settings.py for the worker side that actually executes them).

Mirrors app/db/database.py's get_db()/SessionLocal shape: a plain
dependency function, injected exclusively via FastAPI Depends(), and
overridable in tests the same way (see tests/conftest.py). Unlike
SessionLocal, the pool can't be created eagerly at import time -- arq's
create_pool() is itself a coroutine (it pings Redis once before
returning) -- so it is created lazily on first Depends() resolution
instead, guarded by an asyncio.Lock against a race between two concurrent
requests both finding it unset.
"""

import asyncio
import logging

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None
_pool_lock = asyncio.Lock()


def build_redis_settings() -> RedisSettings:
    """Shared by both sides of the queue: this module (enqueueing from the
    web container) and app.worker.settings.WorkerSettings (consuming in the
    dedicated worker container) -- both must resolve to the same Valkey
    instance, so the connection parameters live in exactly one place."""
    settings = get_settings()
    return RedisSettings(
        host=settings.valkey_host,
        port=settings.valkey_port,
        password=settings.valkey_password,
        database=settings.valkey_database,
    )


async def get_arq_pool() -> ArqRedis:
    """FastAPI dependency -- inject via Depends(get_arq_pool), never import
    or call directly from router code. Declare this dependency AFTER any
    auth/permission Depends() on the same route: FastAPI resolves
    dependencies in declaration order, and creating this pool costs a real
    Redis round-trip on the very first request after process start, which
    an already-rejected (401/403) request must never pay for."""
    global _pool  # noqa: PLW0603 -- lazy singleton, mirrors app/db/database.py's own module-level engine/SessionLocal, just async-created here since create_pool() must be awaited
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await create_pool(build_redis_settings())
            logger.info("ARQ pool created (enqueue side).")
    return _pool


async def close_arq_pool() -> None:
    """Called from main.py's lifespan shutdown. A no-op if no request ever
    actually created the pool (e.g. a process instance that never happened
    to enqueue anything before shutting down)."""
    global _pool  # noqa: PLW0603 -- releases the singleton set up in get_arq_pool()
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("ARQ pool closed.")
