"""Thin async wrappers around app.core.mailer's send_* functions,
registered as arq on-demand jobs (WorkerSettings.functions) and enqueued
from router code via app.api.job_queue.JobQueue.enqueue(). Arq addresses
each wrapper by its own __name__ -- e.g. app/api/router_includes/auth.py's
forgot_password() enqueues send_password_reset_email_task.

Every argument passed through JobQueue.enqueue() must be accepted by the
queue's JSON serializer (app.core.job_serialization): plain str/int/list
values, mailer.BookingCanceledMailEntry and Redacted.

A mail that fails on a transient transport error (the relay is unreachable,
the connection drops, the server answers with an SMTP error) is tried again
a few times with a growing delay; arq itself would mark the job failed and the
mail would be lost. A configuration error (for example a relay without
STARTTLS) is not retried.
"""

import smtplib
from typing import TYPE_CHECKING

from arq import Retry
from starlette.concurrency import run_in_threadpool

from app.core import mailer

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.core.redacted import Redacted

# Must stay below the worker's max_tries (arq default 5).
_MAIL_MAX_TRIES = 4
_MAIL_RETRY_DELAY_SECONDS = 120


async def _send_with_retry[**P](
    ctx: dict[str, object],
    send: Callable[P, None],
    *args: P.args,
    **kwargs: P.kwargs,
) -> None:
    try:
        await run_in_threadpool(send, *args, **kwargs)
    except (smtplib.SMTPException, OSError) as exc:
        job_try = ctx.get("job_try")
        attempt = job_try if isinstance(job_try, int) else 1
        if attempt >= _MAIL_MAX_TRIES:
            raise
        raise Retry(defer=_MAIL_RETRY_DELAY_SECONDS * attempt) from exc


async def send_new_registration_notice_task(
    ctx: dict[str, object],
    *,
    surname: str,
    givenname: str,
    email: str,
    phone: str | None,
) -> None:
    await _send_with_retry(
        ctx,
        mailer.send_new_registration_notice,
        surname=surname,
        givenname=givenname,
        email=email,
        phone=phone,
    )


async def send_registration_account_exists_email_task(
    ctx: dict[str, object], to_email: str
) -> None:
    await _send_with_retry(ctx, mailer.send_registration_account_exists_email, to_email)


async def send_registration_entry_exists_email_task(
    ctx: dict[str, object], to_email: str, givenname: str, surname: str
) -> None:
    await _send_with_retry(
        ctx,
        mailer.send_registration_entry_exists_email,
        to_email,
        givenname=givenname,
        surname=surname,
    )


async def send_verification_email_task(
    ctx: dict[str, object],
    to_email: str,
    verify_url: Redacted,
) -> None:
    # verify_url arrives wrapped in Redacted so arq's own job-start/-finish
    # logging (which reprs every argument) never shows the raw magic-link
    # token in cleartext -- unwrapped here, right before the one place
    # that actually needs the real value.
    await _send_with_retry(
        ctx, mailer.send_verification_email, to_email, verify_url.value
    )


async def send_password_reset_email_task(
    ctx: dict[str, object],
    to_email: str,
    reset_url: Redacted,
) -> None:
    # See send_verification_email_task above for why this arrives wrapped.
    await _send_with_retry(
        ctx, mailer.send_password_reset_email, to_email, reset_url.value
    )


async def send_booked_or_standby_canceled_email_task(
    ctx: dict[str, object],
    to_emails: list[str],
    canceling_user_name: str,
    entry: mailer.BookingCanceledMailEntry,
) -> None:
    await _send_with_retry(
        ctx,
        mailer.send_booked_or_standby_canceled_email,
        to_emails,
        canceling_user_name,
        entry,
    )


async def send_user_message_email_task(
    ctx: dict[str, object],
    to_emails: list[str],
    sender_name: str,
    message: str,
) -> None:
    await _send_with_retry(
        ctx, mailer.send_user_message_email, to_emails, sender_name, message
    )
