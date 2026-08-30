import asyncio
from unittest.mock import AsyncMock

import pytest

import app.core.arq_pool as arq_pool_module
from main import app, lifespan


@pytest.fixture(autouse=True)
def _ensure_no_leftover_pool():
    arq_pool_module._pool = None
    yield
    arq_pool_module._pool = None


def test_lifespan_completes_without_creating_a_pool_if_never_used():
    # Nothing inside the lifespan body itself ever calls get_arq_pool() --
    # the pool is created lazily, only on first Depends() resolution during
    # an actual request (see app.core.arq_pool's own docstring). A process
    # that starts up and shuts down without ever enqueueing a job must not
    # be forced to open a Redis connection just to exit cleanly.
    async def _run() -> None:
        async with lifespan(app):
            assert arq_pool_module._pool is None
        assert arq_pool_module._pool is None

    asyncio.run(_run())


def test_lifespan_closes_arq_pool_on_exit_if_one_was_created():
    fake_pool = AsyncMock()
    arq_pool_module._pool = fake_pool

    async def _run() -> None:
        async with lifespan(app):
            pass

    asyncio.run(_run())

    fake_pool.aclose.assert_awaited_once()
    assert arq_pool_module._pool is None
