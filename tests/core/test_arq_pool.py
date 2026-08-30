import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import app.core.arq_pool as arq_pool_module
from app.core.arq_pool import build_redis_settings, close_arq_pool, get_arq_pool
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_pool_state():
    arq_pool_module._pool = None
    yield
    arq_pool_module._pool = None


def test_build_redis_settings_uses_configured_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VALKEY_HOST", "valkey.internal")
    monkeypatch.setenv("VALKEY_PORT", "6380")
    monkeypatch.setenv("VALKEY_PASSWORD", "s3cret")
    monkeypatch.setenv("VALKEY_DATABASE", "2")
    get_settings.cache_clear()

    settings = build_redis_settings()

    assert settings.host == "valkey.internal"
    assert settings.port == 6380
    assert settings.password == "s3cret"
    assert settings.database == 2


def test_get_arq_pool_returns_the_same_instance_on_repeated_calls():
    fake_pool = AsyncMock()
    with patch.object(
        arq_pool_module, "create_pool", AsyncMock(return_value=fake_pool)
    ) as mock_create_pool:
        first = asyncio.run(get_arq_pool())
        second = asyncio.run(get_arq_pool())

    assert first is fake_pool
    assert second is fake_pool
    mock_create_pool.assert_called_once()


def test_get_arq_pool_creates_only_once_under_concurrent_first_callers():
    fake_pool = AsyncMock()
    mock_create_pool = AsyncMock(return_value=fake_pool)

    async def _run() -> None:
        results = await asyncio.gather(*(get_arq_pool() for _ in range(5)))
        assert all(result is fake_pool for result in results)

    with patch.object(arq_pool_module, "create_pool", mock_create_pool):
        asyncio.run(_run())

    mock_create_pool.assert_called_once()


def test_close_arq_pool_is_a_no_op_if_nothing_was_ever_created():
    # Must not raise even though _pool is None -- a process that never
    # enqueues anything before shutting down must still shut down cleanly.
    asyncio.run(close_arq_pool())
    assert arq_pool_module._pool is None


def test_close_arq_pool_closes_and_clears_an_existing_pool():
    fake_pool = AsyncMock()
    arq_pool_module._pool = fake_pool

    asyncio.run(close_arq_pool())

    fake_pool.aclose.assert_awaited_once()
    assert arq_pool_module._pool is None
