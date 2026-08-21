import asyncio
import logging
import re
from zoneinfo import ZoneInfo

import pytest
from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_SUBMITTED,
    JobEvent,
)
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core import scheduler as scheduler_module
from app.core.config import get_settings
from app.core.scheduler import (
    JOB_DESCRIPTIONS,
    _acquire_scheduler_lock,
    _log_job_outcome,
    get_scheduled_jobs,
    scheduler,
    start_scheduler,
    stop_scheduler,
)

_NEXT_RUN_PATTERN = re.compile(r"^\d{2}\.\d{2}\.\d{4}, \d{2}:\d{2}$")
_ALWAYS_ON_JOB_ID = "purge_stale_booking_requests"
_PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP = {
    "notify_upcoming_booking_status",
    "purge_expired_password_reset_tokens",
    "purge_old_request_logs",
    "backup_koofr",
}
_NON_PRODUCTION_ONLY_JOB_IDS = {"downsync"}


@pytest.fixture(autouse=True)
def _ensure_scheduler_stopped():
    yield
    stop_scheduler()


def test_acquire_scheduler_lock_is_noop_under_sqlite():
    # The test DB (see conftest.py) is always SQLite -- the advisory-lock
    # branch only activates once Phase 2 (Postgres) is in place.
    assert _acquire_scheduler_lock() is True


def test_scheduler_uses_app_timezone():
    # Regression guard: the scheduler-wide default must actually be set
    # (User-reported bug, 2026-08-13 -- jobs without their own explicit
    # `timezone=` kwarg were silently interpreted in the container's local
    # tz instead of Settings.app_timezone, causing a 2-hour Vienna-CEST
    # offset on their displayed/actual run times).
    assert scheduler.timezone == ZoneInfo(get_settings().app_timezone)


def test_purge_stale_booking_requests_uses_a_deterministic_cron_trigger(
    monkeypatch: pytest.MonkeyPatch,
):
    # Regression guard: an IntervalTrigger anchors its first fire to
    # whatever moment start_scheduler() happened to run, so the exact
    # minute-past-the-hour would drift with every container restart
    # (User-reported, 2026-08-13). Must be a fixed-minute CronTrigger.
    monkeypatch.setenv("APP_ENVIRONMENT", "test")

    async def _run() -> None:
        start_scheduler()
        job = scheduler.get_job("purge_stale_booking_requests")
        assert job is not None
        assert isinstance(job.trigger, CronTrigger)
        assert not isinstance(job.trigger, IntervalTrigger)
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_start_and_stop_scheduler_toggle_running_state():
    # osa-backend's test suite is otherwise fully synchronous (TestClient,
    # not AsyncClient -- 1:1 vb-api), but AsyncIOScheduler is an inherently
    # async API regardless of that -- driving it via a single asyncio.run()
    # call is simpler than pulling in pytest-asyncio for just this one test.
    async def _run() -> None:
        assert scheduler.running is False

        start_scheduler()
        assert scheduler.running is True
        # Under the test env (APP_ENVIRONMENT is "test" here, see
        # conftest.py): the always-on job plus downsync (registered whenever
        # NOT production, see test_downsync_job_registers_outside_production)
        # -- the other three, like backup_koofr below, are production-only
        # (see test_production_only_jobs_register_in_production).
        assert {job.id for job in scheduler.get_jobs()} == {
            "purge_stale_booking_requests",
            "downsync",
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


_PRODUCTION_ONLY_JOB_IDS = {
    "notify_upcoming_booking_status",
    "purge_expired_password_reset_tokens",
    "purge_old_request_logs",
}


def test_production_only_jobs_register_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")

    async def _run() -> None:
        start_scheduler()
        assert {job.id for job in scheduler.get_jobs()} >= _PRODUCTION_ONLY_JOB_IDS
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_production_only_jobs_do_not_register_outside_production(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")

    async def _run() -> None:
        start_scheduler()
        assert _PRODUCTION_ONLY_JOB_IDS.isdisjoint(
            {job.id for job in scheduler.get_jobs()}
        )
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_production_only_jobs_deregister_if_a_previous_call_was_production(
    monkeypatch: pytest.MonkeyPatch,
):
    # Mirrors test_backup_koofr_job_deregisters_if_a_previous_call_was_production
    # above -- same _sync_job_registration() helper, exercised here for the
    # three newly-gated jobs instead of backup_koofr. The helper's stray-job
    # removal branch itself is already covered by
    # test_backup_koofr_job_is_explicitly_removed_if_stray (shared code, no
    # need to duplicate that case per job).
    monkeypatch.setenv("APP_ENVIRONMENT", "production")

    async def _run() -> None:
        start_scheduler()
        assert {job.id for job in scheduler.get_jobs()} >= _PRODUCTION_ONLY_JOB_IDS
        stop_scheduler()
        await asyncio.sleep(0)

        monkeypatch.setenv("APP_ENVIRONMENT", "test")
        get_settings.cache_clear()
        start_scheduler()
        assert _PRODUCTION_ONLY_JOB_IDS.isdisjoint(
            {job.id for job in scheduler.get_jobs()}
        )
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


def test_job_descriptions_covers_every_registrable_job_id():
    # Guards against a future new job being added to start_scheduler()
    # without a matching JOB_DESCRIPTIONS entry -- the admin Scheduler
    # overview would silently show it with description=None otherwise.
    all_registrable_job_ids = {
        _ALWAYS_ON_JOB_ID,
        *_PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP,
        *_NON_PRODUCTION_ONLY_JOB_IDS,
    }
    assert all_registrable_job_ids <= JOB_DESCRIPTIONS.keys()


def test_every_registered_job_inherits_the_scheduler_default_timezone(
    monkeypatch: pytest.MonkeyPatch,
):
    # Regression guard for the same bug as test_scheduler_uses_app_timezone
    # above, but at the per-job level: every cron-triggered job must
    # actually resolve to Settings.app_timezone, not just the scheduler
    # object itself (a job could in principle still override it locally).
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    expected_tz = ZoneInfo(get_settings().app_timezone)

    async def _run() -> None:
        start_scheduler()
        for job in scheduler.get_jobs():
            assert job.trigger.timezone == expected_tz, job.id
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_get_scheduled_jobs_returns_empty_list_when_scheduler_not_started():
    assert get_scheduled_jobs() == []


def test_get_scheduled_jobs_includes_always_on_job_with_description(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")

    async def _run() -> None:
        start_scheduler()
        jobs_by_id = {job["id"]: job for job in get_scheduled_jobs()}
        assert (
            jobs_by_id[_ALWAYS_ON_JOB_ID]["description"]
            == (JOB_DESCRIPTIONS[_ALWAYS_ON_JOB_ID])
        )
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_get_scheduled_jobs_includes_production_only_jobs_with_descriptions(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("BACKUP_ENABLED", "true")

    async def _run() -> None:
        start_scheduler()
        jobs_by_id = {job["id"]: job for job in get_scheduled_jobs()}
        assert jobs_by_id.keys() >= _PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP
        assert all(
            jobs_by_id[job_id]["description"]
            for job_id in _PRODUCTION_ONLY_JOB_IDS_WITH_BACKUP
        )
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_get_scheduled_jobs_next_run_is_formatted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")

    async def _run() -> None:
        start_scheduler()
        job = next(
            job for job in get_scheduled_jobs() if job["id"] == _ALWAYS_ON_JOB_ID
        )
        assert job["next_run"] is not None
        assert _NEXT_RUN_PATTERN.match(job["next_run"])
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_get_scheduled_jobs_returns_empty_list_after_stop(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")

    async def _run() -> None:
        start_scheduler()
        assert get_scheduled_jobs() != []
        stop_scheduler()
        await asyncio.sleep(0)
        assert get_scheduled_jobs() == []

    asyncio.run(_run())


def test_downsync_job_registers_outside_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")

    async def _run() -> None:
        start_scheduler()
        assert "downsync" in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_downsync_job_does_not_register_in_production(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")

    async def _run() -> None:
        start_scheduler()
        assert "downsync" not in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_downsync_job_deregisters_when_a_later_call_becomes_production(
    monkeypatch: pytest.MonkeyPatch,
):
    # Mirrors test_backup_koofr_job_deregisters_if_a_previous_call_was_production
    # in reverse direction -- downsync is the mirror-image job (registered
    # outside production instead of inside it), same idempotency contract.
    monkeypatch.setenv("APP_ENVIRONMENT", "test")

    async def _run() -> None:
        start_scheduler()
        assert "downsync" in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        get_settings.cache_clear()
        start_scheduler()
        assert "downsync" not in {job.id for job in scheduler.get_jobs()}
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_downsync_job_runs_one_hour_after_the_backup_hour(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("BACKUP_HOUR", "3")
    monkeypatch.setenv("BACKUP_MINUTE", "15")

    async def _run() -> None:
        start_scheduler()
        job = scheduler.get_job("downsync")
        assert job is not None
        assert isinstance(job.trigger, CronTrigger)
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert fields["hour"] == "4"
        assert fields["minute"] == "15"
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_downsync_job_wraps_the_hour_at_the_day_boundary(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("BACKUP_HOUR", "23")

    async def _run() -> None:
        start_scheduler()
        job = scheduler.get_job("downsync")
        assert job is not None
        fields = {field.name: str(field) for field in job.trigger.fields}
        assert fields["hour"] == "0"
        stop_scheduler()
        await asyncio.sleep(0)

    asyncio.run(_run())
