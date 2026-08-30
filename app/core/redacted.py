"""Wrapper for an arq job argument that must never appear in cleartext in
arq's own default job-start/job-finish logging.

arq's Worker logs every job invocation at INFO level via
arq.utils.args_to_string(), which calls repr() on each positional
argument -- fine for ordinary business data, but a magic-link URL
(password-reset/email-verification token) IS a bearer credential for the
duration of its TTL, and ends up sitting in plain text in worker logs
otherwise. Wrapping such a value in Redacted before passing it to
enqueue_job() keeps arq's log line free of the actual token while the
task body itself still gets the real value via .value.
"""

from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class Redacted:
    value: str

    def __repr__(self) -> str:
        return "<redacted>"
