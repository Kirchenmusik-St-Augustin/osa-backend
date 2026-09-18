import logging
import threading
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api.job_queue import JobQueue, get_job_queue
from app.core.arq_pool import get_arq_pool
from app.core.redacted import Redacted


async def sample_job(ctx: dict[str, object], recipient: str, secret: Redacted) -> None:
    """Stand-in for an arq job function -- only its __name__ and signature matter."""


class _Pool:
    def __init__(self) -> None:
        self.enqueue_job = AsyncMock(return_value=None)


@pytest.fixture
def pool() -> _Pool:
    return _Pool()


@pytest.fixture
def handler_thread_ids() -> list[int]:
    return []


@pytest.fixture
def job_client(pool: _Pool, handler_thread_ids: list[int]) -> TestClient:
    """A throwaway app with one plain `def` route -- exactly the shape every
    real router now has -- so the JobQueue contract is tested in isolation."""
    test_app = FastAPI()

    async def _pool_override() -> _Pool:
        return pool

    test_app.dependency_overrides[get_arq_pool] = _pool_override

    @test_app.post("/send")
    def send(job_queue: Annotated[JobQueue, Depends(get_job_queue)]) -> dict[str, str]:
        handler_thread_ids.append(threading.get_ident())
        job_queue.enqueue(sample_job, "a@example.test", Redacted("s3cret"))
        return {"status": "ok"}

    return TestClient(test_app)


def test_enqueue_dispatches_job_by_function_name_with_arguments(
    job_client: TestClient, pool: _Pool
):
    response = job_client.post("/send")

    assert response.status_code == 200
    pool.enqueue_job.assert_awaited_once_with(
        "sample_job", "a@example.test", Redacted("s3cret")
    )


def test_enqueue_runs_on_the_event_loop_not_in_the_handler_thread(
    job_client: TestClient, pool: _Pool, handler_thread_ids: list[int]
):
    """The handler is a sync `def` and thus runs in the threadpool; the
    pooled Redis connection belongs to the event loop, so the enqueue itself
    must be awaited there, not in the handler's worker thread."""
    enqueue_thread_ids: list[int] = []

    async def _record_thread(*_args: object, **_kwargs: object) -> None:
        enqueue_thread_ids.append(threading.get_ident())

    pool.enqueue_job.side_effect = _record_thread

    job_client.post("/send")

    assert len(handler_thread_ids) == 1
    assert len(enqueue_thread_ids) == 1
    assert enqueue_thread_ids != handler_thread_ids


def test_redis_failure_is_logged_without_arguments_and_does_not_fail_response(
    job_client: TestClient, pool: _Pool, caplog: pytest.LogCaptureFixture
):
    pool.enqueue_job.side_effect = RedisConnectionError("valkey unreachable")

    with caplog.at_level(logging.ERROR, logger="app.api.job_queue"):
        response = job_client.post("/send")

    assert response.status_code == 200
    assert "sample_job" in caplog.text
    assert "a@example.test" not in caplog.text
    assert "s3cret" not in caplog.text


def test_non_redis_errors_are_not_swallowed(job_client: TestClient, pool: _Pool):
    pool.enqueue_job.side_effect = RuntimeError("programming error")

    with pytest.raises(RuntimeError, match="programming error"):
        job_client.post("/send")
