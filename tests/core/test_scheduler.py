import asyncio

import pytest

from app.core import scheduler as scheduler_module
from app.core.scheduler import (
    _acquire_scheduler_lock,
    scheduler,
    start_scheduler,
    stop_scheduler,
)


@pytest.fixture(autouse=True)
def _ensure_scheduler_stopped():
    yield
    stop_scheduler()


def test_acquire_scheduler_lock_is_noop_under_sqlite():
    # The test DB (see conftest.py) is always SQLite -- the advisory-lock
    # branch only activates once Phase 2 (Postgres) is in place.
    assert _acquire_scheduler_lock() is True


async def test_start_and_stop_scheduler_toggle_running_state():
    assert scheduler.running is False

    start_scheduler()
    assert scheduler.running is True
    assert scheduler.get_jobs() == []

    stop_scheduler()
    # AsyncIOScheduler.shutdown() defers the actual state flip via
    # call_soon_threadsafe -- give the event loop one tick to process it
    # before asserting.
    await asyncio.sleep(0)
    assert scheduler.running is False


def test_start_scheduler_skips_when_lock_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(scheduler_module, "_acquire_scheduler_lock", lambda: False)

    start_scheduler()

    assert scheduler.running is False


class _FakeResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _FakeConnection:
    def __init__(self, *, acquired: bool) -> None:
        self._acquired = acquired
        self.closed = False

    def execute(self, *_args: object, **_kwargs: object) -> _FakeResult:
        return _FakeResult(self._acquired)

    def close(self) -> None:
        self.closed = True


class _FakeDialect:
    name = "postgresql"


class _FakeEngine:
    dialect = _FakeDialect()

    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> _FakeConnection:
        return self._connection


def test_acquire_scheduler_lock_holds_connection_under_postgresql(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_connection = _FakeConnection(acquired=True)
    monkeypatch.setattr(scheduler_module, "engine", _FakeEngine(fake_connection))

    assert _acquire_scheduler_lock() is True
    assert scheduler_module._scheduler_lock_conn is fake_connection

    stop_scheduler()

    assert fake_connection.closed is True
    assert scheduler_module._scheduler_lock_conn is None


def test_acquire_scheduler_lock_returns_false_when_already_held(
    monkeypatch: pytest.MonkeyPatch,
):
    fake_connection = _FakeConnection(acquired=False)
    monkeypatch.setattr(scheduler_module, "engine", _FakeEngine(fake_connection))

    assert _acquire_scheduler_lock() is False
    assert fake_connection.closed is True
