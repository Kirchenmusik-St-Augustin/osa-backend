"""Request-scoped facade for handing arq jobs to the worker container from
plain `def` route handlers.

Enqueueing is a coroutine (`ArqRedis.enqueue_job`), which would force every
route that sends a mail to be `async def` -- and with it every blocking
SQLAlchemy call in that route into `run_in_threadpool`. Instead the handler
stays synchronous (FastAPI runs it in its own threadpool) and registers the
enqueue on FastAPI's `BackgroundTasks`. Starlette awaits coroutine
functions registered there directly on the event loop, right after the
response has been sent -- the same loop that owns the pooled Redis
connection, so no thread-to-loop bridging is needed.

Consequences callers must know:
- The response never waits on the queue. A failed enqueue therefore cannot
  change the HTTP status any more; it is logged (see `_enqueue`) and the job
  is lost, just like the fire-and-forget mail sending this replaced.
- Every argument is evaluated when `JobQueue.enqueue()` is called, inside
  the handler -- pass plain values, never ORM objects (the request's DB
  session is closed by the time the background task runs).
"""

import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Concatenate

from arq.connections import ArqRedis
from fastapi import BackgroundTasks, Depends
from redis.exceptions import RedisError

from app.core.arq_pool import get_arq_pool

logger = logging.getLogger(__name__)

type JobContext = dict[str, object]


async def _enqueue(
    arq_pool: ArqRedis,
    function_name: str,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    """Logs the job NAME only, never its arguments: they carry magic-link
    tokens and mail bodies (see app.worker.tasks and app.core.redacted)."""
    try:
        # The kwargs are the job function's own keyword parameters (typed by
        # JobQueue.enqueue), which never start with an underscore -- so they
        # cannot collide with enqueue_job's underscore-prefixed queue options,
        # something Pyright cannot see through a plain dict.
        await arq_pool.enqueue_job(function_name, *args, **kwargs)  # pyright: ignore[reportArgumentType]
    except RedisError:
        logger.exception(
            "Could not enqueue ARQ job %r; the job is lost.", function_name
        )


class JobQueue:
    def __init__(self, background_tasks: BackgroundTasks, arq_pool: ArqRedis) -> None:
        self._background_tasks = background_tasks
        self._arq_pool = arq_pool

    def enqueue[**P](
        self,
        job: Callable[Concatenate[JobContext, P], Coroutine[object, object, None]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> None:
        """`job` is one of the coroutine functions registered in
        app.worker.settings.WorkerSettings.functions; arq addresses it by
        its `__name__` and supplies its leading `ctx` argument itself, so
        `args`/`kwargs` are checked against the job's remaining parameters.
        They must be picklable (arq's job serializer)."""
        self._background_tasks.add_task(
            _enqueue, self._arq_pool, job.__name__, args, kwargs
        )


def get_job_queue(
    background_tasks: BackgroundTasks,
    arq_pool: Annotated[ArqRedis, Depends(get_arq_pool)],
) -> JobQueue:
    """FastAPI dependency -- inject via Depends(get_job_queue). Declare it
    AFTER any auth/permission Depends() on the same route: FastAPI resolves
    dependencies in declaration order, and the very first resolution after
    process start costs a real Redis round-trip (see get_arq_pool), which an
    already-rejected (401/403) request must never pay for."""
    return JobQueue(background_tasks, arq_pool)
