import logging

from app.worker import scheduled_or_triggered_log_filter
from app.worker.scheduled_or_triggered_log_filter import (
    install_scheduled_or_triggered_log_filter,
)


def _make_arq_worker_record(
    msg: str, args: tuple[object, ...], *, level: int = logging.INFO
) -> logging.LogRecord:
    return logging.LogRecord(
        name="arq.worker",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def test_cron_start_gets_scheduled_prefix():
    record = _make_arq_worker_record(
        "%6.2fs → %s(%s)%s", (0.01, "purge_stale_booking_requests", "", "")
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[scheduled] %6.2fs → %s(%s)%s"


def test_cron_success_gets_scheduled_prefix():
    record = _make_arq_worker_record(
        "%6.2fs ← %s ● %s", (0.02, "purge_stale_booking_requests", "")
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[scheduled] %6.2fs ← %s ● %s"


def test_cron_retry_gets_scheduled_prefix():
    record = _make_arq_worker_record(
        "%6.2fs ↻ %s retrying job in %0.2fs", (0.03, "backup_koofr", 5.0)
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[scheduled] %6.2fs ↻ %s retrying job in %0.2fs"


def test_cron_abort_gets_scheduled_prefix():
    record = _make_arq_worker_record("%6.2fs ⊘ %s aborted", (0.04, "downsync"))

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[scheduled] %6.2fs ⊘ %s aborted"


def test_cron_failure_gets_scheduled_prefix():
    record = _make_arq_worker_record(
        "%6.2fs ! %s failed, %s: %s",
        (0.05, "purge_old_request_logs", "ValueError", "boom"),
        level=logging.ERROR,
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[scheduled] %6.2fs ! %s failed, %s: %s"


def test_cron_cancelled_will_be_run_again_gets_scheduled_prefix():
    # Ref-based template found only by re-diffing against the installed
    # arq 0.28.0 source -- not covered by a naive "5 known templates"
    # assumption (Retry vs. bare cancellation are two different lines).
    record = _make_arq_worker_record(
        "%6.2fs ↻ %s cancelled, will be run again",
        (0.06, "notify_upcoming_booking_status"),
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[scheduled] %6.2fs ↻ %s cancelled, will be run again"


def test_cron_max_retries_exceeded_gets_scheduled_prefix():
    # Also only found via live re-verification -- logged at WARNING, not
    # via logger.exception like the other failure path.
    record = _make_arq_worker_record(
        "%6.2fs ! %s max retries %d exceeded",
        (0.07, "purge_expired_password_reset_tokens", 5),
        level=logging.WARNING,
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[scheduled] %6.2fs ! %s max retries %d exceeded"


def test_on_demand_start_gets_triggered_prefix():
    record = _make_arq_worker_record(
        "%6.2fs → %s(%s)%s", (0.01, "a1b2c3d4:send_verification_email_task", "", "")
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[triggered] %6.2fs → %s(%s)%s"


def test_on_demand_failure_gets_triggered_prefix():
    record = _make_arq_worker_record(
        "%6.2fs ! %s failed, %s: %s",
        (0.08, "a1b2c3d4:send_password_reset_email_task", "ValueError", "boom"),
        level=logging.ERROR,
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "[triggered] %6.2fs ! %s failed, %s: %s"


def test_records_from_other_loggers_are_left_unchanged():
    record = logging.LogRecord(
        name="app.services.backup_service",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%6.2fs → %s(%s)%s",
        args=(0.01, "job_id:some_function", "", ""),
        exc_info=None,
    )

    result = scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(
        record
    )

    assert result is True
    assert record.msg == "%6.2fs → %s(%s)%s"


def test_function_not_found_warning_is_left_unchanged():
    # Same logger, same "%s at args[1]" shape as a cron ref -- but this
    # is function_name, not ref. Must not be misread as an untagged cron
    # line just because it lacks a colon.
    record = _make_arq_worker_record(
        "job %s, function %r not found",
        ("some-job-id", "unknown_function"),
        level=logging.WARNING,
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "job %s, function %r not found"


def test_aborted_before_start_is_left_unchanged():
    # args[1] here is job_id, not ref -- textually distinct from the
    # ref-based "aborted" template (two %s placeholders with a literal
    # ':' vs. a single %s), so the whitelist excludes it naturally.
    record = _make_arq_worker_record(
        "%6.2fs ⊘ %s:%s aborted before start",
        (0.01, "some-job-id", "some_function"),
    )

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "%6.2fs ⊘ %s:%s aborted before start"


def test_non_string_msg_is_left_unchanged():
    # logging.LogRecord.msg accepts any object (lazy %-style formatting
    # permits non-str messages) -- must not raise or misbehave if some
    # future arq release ever logged something other than a plain str.
    record = _make_arq_worker_record("%6.2fs → %s(%s)%s", (0.01, "x", "", ""))
    record.msg = 123  # type: ignore[assignment] -- deliberately malformed for this guard-clause test

    result = scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(
        record
    )

    assert result is True
    assert record.msg == 123


def test_too_few_args_is_left_unchanged():
    # A record whose msg matches a whitelisted template but whose args
    # tuple is too short to contain a ref at index 1 -- must not raise
    # an IndexError.
    record = _make_arq_worker_record("%6.2fs ⊘ %s aborted", (0.01,))

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "%6.2fs ⊘ %s aborted"


def test_non_string_ref_is_left_unchanged():
    # args[1] not being a str would happen only for a record that
    # doesn't actually come from Worker.run_job() -- the guard must
    # still hold rather than crash on `":" in ref`.
    record = _make_arq_worker_record("%6.2fs ⊘ %s aborted", (0.01, 42))

    scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(record)

    assert record.msg == "%6.2fs ⊘ %s aborted"


def test_filter_always_returns_true():
    record = _make_arq_worker_record(
        "%6.2fs → %s(%s)%s", (0.01, "purge_stale_booking_requests", "", "")
    )

    result = scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter().filter(
        record
    )

    assert result is True


def test_install_is_idempotent_across_repeated_calls():
    arq_worker_logger = logging.getLogger("arq.worker")
    original_filters = list(arq_worker_logger.filters)
    try:
        install_scheduled_or_triggered_log_filter()
        install_scheduled_or_triggered_log_filter()

        installed = [
            f
            for f in arq_worker_logger.filters
            if isinstance(
                f, scheduled_or_triggered_log_filter._ScheduledOrTriggeredLogFilter
            )
        ]
        assert len(installed) == 1
    finally:
        # 'arq.worker' is a process-wide singleton via logging.getLogger()
        # -- restore its filter list so this test doesn't leak state into
        # whatever test module happens to run after it.
        arq_worker_logger.filters = original_filters
