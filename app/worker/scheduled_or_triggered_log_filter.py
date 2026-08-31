"""Tags arq's job-lifecycle log lines with a [scheduled]/[triggered]
prefix, so worker logs make it visually obvious whether a given job run
was one of this worker's cron jobs or was fired on demand via
enqueue_job() (e.g. a verification/reset/notification mail).

arq (0.28.0, arq/worker.py) logs every job-lifecycle event through
logging.getLogger('arq.worker'), always with the job's `ref` as the
message's second positional argument (record.args[1]; args[0] is always
the elapsed time, interpolated via '%6.2fs'). Worker.run_job() computes
`ref` differently depending on the job's origin:

    if hasattr(function, 'next_run'):
        # cron_job
        ref = function_name
        ...
    else:
        ref = f'{job_id}:{function_name}'
        ...

Cron jobs log only the bare function name; every enqueue_job()-triggered
job logs `job_id:function_name`. Python identifiers can never contain
':', so "does ref contain a colon" is an exact, dependency-free way to
tell the two apart -- no need to inspect Redis, the cron catalog, or arq
internals beyond this one log line's own arguments.

This filter only acts on an explicit whitelist of the 7 message templates
below, verified directly against the installed arq 0.28.0 source. Two
same-logger, similarly-shaped lines must NEVER be tagged and are excluded
by the exact-match whitelist rather than by pattern-guessing:

    * 'job %s, function %r not found' (args[1] is function_name, not ref)
    * '%6.2fs ⊘ %s:%s aborted before start' (args[1] is job_id, not
      ref; also textually distinct from the ref-based '%6.2fs ⊘ %s
      aborted' template below -- two %s placeholders with a literal ':'
      between them, not one)

Whitelisting exact message templates (rather than pattern-matching
rendered text) means a future arq upgrade that changes wording just
silently stops matching -- fails safe (lines pass through untagged)
instead of ever mistagging a line it doesn't actually recognize. Any arq
upgrade should re-diff arq/worker.py's logger.info/warning/exception
calls against the set below.
"""

import logging

_ARQ_WORKER_LOGGER_NAME = "arq.worker"

_JOB_LIFECYCLE_MESSAGE_TEMPLATES: frozenset[str] = frozenset(
    {
        "%6.2fs → %s(%s)%s",  # job started
        "%6.2fs ↻ %s retrying job in %0.2fs",  # Retry raised
        "%6.2fs ⊘ %s aborted",  # aborted mid-run
        "%6.2fs ↻ %s cancelled, will be run again",  # cancelled+retried
        "%6.2fs ! %s failed, %s: %s",  # unhandled exception
        "%6.2fs ← %s ● %s",  # succeeded
        "%6.2fs ! %s max retries %d exceeded",  # gave up after max_tries
    }
)


class _ScheduledOrTriggeredLogFilter(logging.Filter):
    """Prefixes arq's 'arq.worker' job-lifecycle lines with [scheduled] or
    [triggered] (see this module's docstring for the full reasoning).
    Installed once via install_scheduled_or_triggered_log_filter() below.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != _ARQ_WORKER_LOGGER_NAME:
            return True
        if not isinstance(record.msg, str):
            return True
        if record.msg not in _JOB_LIFECYCLE_MESSAGE_TEMPLATES:
            return True
        if not isinstance(record.args, tuple) or len(record.args) < 2:
            return True

        ref = record.args[1]
        if not isinstance(ref, str):
            return True

        origin = "triggered" if ":" in ref else "scheduled"
        record.msg = f"[{origin}] {record.msg}"
        return True


def install_scheduled_or_triggered_log_filter() -> None:
    """Registers _ScheduledOrTriggeredLogFilter on 'arq.worker' exactly
    once. Idempotent (checks for an already-installed instance first) so
    calling this more than once never prefixes a line twice.

    Installed on the logger itself (Logger.addFilter()), not on a
    handler: Logger.handle() evaluates a logger's own filters exactly
    once per log call, before propagating to any handlers -- this runs
    once regardless of how many handlers end up attached later (e.g. by
    arq's own logging.config.dictConfig() call, which runs after this
    module is imported but only (re)configures the 'arq' logger, not
    'arq.worker' itself).
    """
    arq_worker_logger = logging.getLogger(_ARQ_WORKER_LOGGER_NAME)
    if any(
        isinstance(existing_filter, _ScheduledOrTriggeredLogFilter)
        for existing_filter in arq_worker_logger.filters
    ):
        return
    arq_worker_logger.addFilter(_ScheduledOrTriggeredLogFilter())
