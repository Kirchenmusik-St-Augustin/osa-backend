import asyncio
import logging

import pytest
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_SUBMITTED,
    JobEvent,
)

from app.core import scheduler as scheduler_module
from app.core.config import get_settings
from app.core.scheduler import (
    _acquire_scheduler_lock,
    _log_job_outcome,
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


def test_start_and_stop_scheduler_toggle_running_state():
    # osa-backend's test suite is otherwise fully synchronous (TestClient,
    # not AsyncClient -- 1:1 vb-api), but AsyncIOScheduler is an inherently
    # async API regardless of that -- driving it via a single asyncio.run()
    # call is simpler than pulling in pytest-asyncio for just this one test.
    async def _run() -> None:
        assert scheduler.running is False

        start_scheduler()
        assert scheduler.running is True
        assert {job.id for job in scheduler.get_jobs()} == {
            "purge_stale_booking_requests",
            "notify_upcoming_booking_status",
            "purge_expired_password_reset_tokens",
            "purge_old_request_logs",
        }

        stop_scheduler()
        # AsyncIOScheduler.shutdown() defers the actual state flip via
        # call_soon_threadsafe -- give the event loop one tick to process
        # it before asserting.
        await asyncio.sleep(0)
        assert scheduler.running is False

    asyncio.run(_run())


def test_log_job_outcome_logs_submitted_as_starting(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        _log_job_outcome(JobEvent(EVENT_JOB_SUBMITTED, "some_job", "default"))
    assert "starting" in caplog.text
    assert "some_job" in caplog.text


def test_log_job_outcome_logs_executed_as_finished(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        _log_job_outcome(JobEvent(EVENT_JOB_EXECUTED, "some_job", "default"))
    assert "finished" in caplog.text


def test_log_job_outcome_logs_error_as_failed(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.ERROR):
        _log_job_outcome(JobEvent(EVENT_JOB_ERROR, "some_job", "default"))
    assert "failed" in caplog.text


def test_backup_koofr_job_registers_in_production_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "true")

    async def _run() -> None:
        start_scheduler()
        assert "backup_koofr" in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        # See test_start_and_stop_scheduler_toggle_running_state above --
        # shutdown() must complete on THIS loop before it closes, or the
        # module-level scheduler is left in a broken state for later tests.
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_backup_koofr_job_does_not_register_outside_production(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("BACKUP_ENABLED", "true")

    async def _run() -> None:
        start_scheduler()
        assert "backup_koofr" not in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_backup_koofr_job_does_not_register_when_disabled_even_in_production(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "false")

    async def _run() -> None:
        start_scheduler()
        assert "backup_koofr" not in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_backup_koofr_job_is_explicitly_removed_if_stray(
    monkeypatch: pytest.MonkeyPatch,
):
    # Targeted unit test for start_scheduler()'s defensive removal branch
    # (app/core/scheduler.py's `if scheduler.get_job("backup_koofr") is not
    # None: scheduler.remove_job(...)`): seeds a stray job directly, since a
    # realistic stop/restart cycle already clears the jobstore on its own,
    # which would make this branch look unreachable in a more "natural"
    # test.
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("BACKUP_ENABLED", "true")

    async def _run() -> None:
        scheduler.add_job(lambda: None, "date", id="backup_koofr")
        assert scheduler.get_job("backup_koofr") is not None

        start_scheduler()

        assert scheduler.get_job("backup_koofr") is None
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_backup_koofr_job_deregisters_if_a_previous_call_was_production(
    monkeypatch: pytest.MonkeyPatch,
):
    # Guards start_scheduler()'s idempotency across repeated calls against
    # the same module-level scheduler instance -- a job registered under
    # one set of conditions must not linger once conditions change.
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "true")

    async def _run() -> None:
        start_scheduler()
        assert "backup_koofr" in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        # get_settings() is lru_cache'd -- the autouse _reset_settings_cache
        # fixture only clears it at test boundaries, not mid-test, so a
        # second start_scheduler() call within this same test needs an
        # explicit clear to actually observe the env change above.
        get_settings.cache_clear()
        start_scheduler()
        assert "backup_koofr" not in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


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
