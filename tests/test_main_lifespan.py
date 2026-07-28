import asyncio

import pytest

from app.core.scheduler import scheduler, stop_scheduler
from main import app, lifespan


@pytest.fixture(autouse=True)
def _ensure_scheduler_stopped():
    stop_scheduler()
    yield
    stop_scheduler()


async def test_lifespan_starts_scheduler_on_entry_and_stops_it_on_exit():
    assert scheduler.running is False

    async with lifespan(app):
        assert scheduler.running is True

    # AsyncIOScheduler.shutdown() defers the actual state flip via
    # call_soon_threadsafe -- give the event loop one tick to process it
    # before asserting.
    await asyncio.sleep(0)
    assert scheduler.running is False
