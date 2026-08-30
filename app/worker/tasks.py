"""Thin async wrappers around app.core.mailer's send_* functions,
registered as arq on-demand jobs (WorkerSettings.functions) and enqueued
from router code that used to call BackgroundTasks.add_task(mailer.send_
...) directly. Each wrapper's own __name__ is what routers pass to
ArqRedis.enqueue_job() -- e.g. app/api/router_includes/auth.py's
forgot_password() enqueues send_password_reset_email_task.__name__.

Every argument passed through enqueue_job() must be picklable (arq's
default job serializer) -- true for every argument below (plain str/list
values, and mailer.BookingCanceledMailEntry, a module-level frozen
dataclass).
"""

from starlette.concurrency import run_in_threadpool

from app.core import mailer


async def send_new_registration_notice_task(
    ctx: dict[str, object],  # noqa: ARG001 -- arq's WorkerCoroutine protocol requires a parameter literally named "ctx" (job context, unused by this job)
    *,
    surname: str,
    givenname: str,
    email: str,
    phone: str | None,
) -> None:
    await run_in_threadpool(
        mailer.send_new_registration_notice,
        surname=surname,
        givenname=givenname,
        email=email,
        phone=phone,
    )


async def send_verification_email_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see send_new_registration_notice_task
    to_email: str,
    verify_url: str,
) -> None:
    await run_in_threadpool(mailer.send_verification_email, to_email, verify_url)


async def send_password_reset_email_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see send_new_registration_notice_task
    to_email: str,
    reset_url: str,
) -> None:
    await run_in_threadpool(mailer.send_password_reset_email, to_email, reset_url)


async def send_booked_or_standby_canceled_email_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see send_new_registration_notice_task
    to_emails: list[str],
    canceling_user_name: str,
    entry: mailer.BookingCanceledMailEntry,
) -> None:
    await run_in_threadpool(
        mailer.send_booked_or_standby_canceled_email,
        to_emails,
        canceling_user_name,
        entry,
    )


async def send_user_message_email_task(
    ctx: dict[str, object],  # noqa: ARG001 -- see send_new_registration_notice_task
    to_emails: list[str],
    sender_name: str,
    message: str,
) -> None:
    await run_in_threadpool(
        mailer.send_user_message_email, to_emails, sender_name, message
    )
