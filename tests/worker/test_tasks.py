import asyncio
import inspect
import smtplib
from datetime import datetime
from unittest.mock import patch

import pytest
from arq import Retry
from arq.worker import Worker

from app.core import mailer
from app.core.redacted import Redacted
from app.worker import tasks


def test_send_new_registration_notice_task_forwards_all_fields():
    with patch.object(mailer, "send_new_registration_notice") as mock_send:
        asyncio.run(
            tasks.send_new_registration_notice_task(
                {},
                surname="Mustermann",
                givenname="Max",
                email="max@example.com",
                phone="0664 1234567",
            )
        )
    mock_send.assert_called_once_with(
        surname="Mustermann",
        givenname="Max",
        email="max@example.com",
        phone="0664 1234567",
    )


def test_send_verification_email_task_forwards_email_and_url():
    with patch.object(mailer, "send_verification_email") as mock_send:
        asyncio.run(
            tasks.send_verification_email_task(
                {},
                "max@example.com",
                Redacted("https://example.com/verify?token=abc"),
            )
        )
    mock_send.assert_called_once_with(
        "max@example.com", "https://example.com/verify?token=abc"
    )


def test_send_password_reset_email_task_forwards_email_and_url():
    with patch.object(mailer, "send_password_reset_email") as mock_send:
        asyncio.run(
            tasks.send_password_reset_email_task(
                {},
                "max@example.com",
                Redacted("https://example.com/reset?token=abc"),
            )
        )
    mock_send.assert_called_once_with(
        "max@example.com", "https://example.com/reset?token=abc"
    )


def test_send_booked_or_standby_canceled_email_task_forwards_all_fields():
    entry = mailer.BookingCanceledMailEntry(
        ordinariumwork_artist_name="Mozart",
        ordinariumwork_name="Requiem",
        schedule=datetime(2026, 9, 1, 10, 0),  # noqa: DTZ001 -- naive wall-clock
        location_name="Dom",
        location_address=None,
        previous_status=1,
        position_name="Sopran",
    )

    with patch.object(mailer, "send_booked_or_standby_canceled_email") as mock_send:
        asyncio.run(
            tasks.send_booked_or_standby_canceled_email_task(
                {}, ["a@example.com", "b@example.com"], "Erika Musterfrau", entry
            )
        )
    mock_send.assert_called_once_with(
        ["a@example.com", "b@example.com"], "Erika Musterfrau", entry
    )


def test_send_user_message_email_task_forwards_all_fields():
    with patch.object(mailer, "send_user_message_email") as mock_send:
        asyncio.run(
            tasks.send_user_message_email_task(
                {}, ["a@example.com"], "Erika Musterfrau", "Hallo!"
            )
        )
    mock_send.assert_called_once_with(["a@example.com"], "Erika Musterfrau", "Hallo!")


def _entry() -> mailer.BookingCanceledMailEntry:
    return mailer.BookingCanceledMailEntry(
        ordinariumwork_artist_name="Mozart",
        ordinariumwork_name="Requiem",
        schedule=datetime(2026, 9, 1, 10, 0),  # noqa: DTZ001 -- naive wall-clock
        location_name="Dom",
        location_address=None,
        previous_status=1,
        position_name="Sopran",
    )


# (task, mailer function it calls, how to call it after the job context)
_MAIL_TASKS = [
    (
        tasks.send_new_registration_notice_task,
        "send_new_registration_notice",
        (),
        {
            "surname": "Mustermann",
            "givenname": "Max",
            "email": "max@example.com",
            "phone": None,
        },
    ),
    (
        tasks.send_verification_email_task,
        "send_verification_email",
        ("max@example.com", Redacted("https://example.com/verify?token=abc")),
        {},
    ),
    (
        tasks.send_password_reset_email_task,
        "send_password_reset_email",
        ("max@example.com", Redacted("https://example.com/reset?token=abc")),
        {},
    ),
    (
        tasks.send_booked_or_standby_canceled_email_task,
        "send_booked_or_standby_canceled_email",
        (["a@example.com"], "Erika Musterfrau", _entry()),
        {},
    ),
    (
        tasks.send_user_message_email_task,
        "send_user_message_email",
        (["a@example.com"], "Erika Musterfrau", "Hallo"),
        {},
    ),
]


@pytest.mark.parametrize(("task", "mailer_function", "args", "kwargs"), _MAIL_TASKS)
class TestMailRetry:
    @pytest.mark.parametrize(
        ("job_try", "expected_defer"), [(1, 120), (2, 240), (3, 360)]
    )
    def test_a_refused_connection_is_retried_with_a_growing_delay(
        self, task, mailer_function, args, kwargs, job_try: int, expected_defer: int
    ):
        with (
            patch.object(
                mailer, mailer_function, side_effect=ConnectionRefusedError("refused")
            ),
            pytest.raises(Retry) as exc_info,
        ):
            asyncio.run(task({"job_try": job_try}, *args, **kwargs))

        assert exc_info.value.defer_score == expected_defer * 1000

    def test_an_smtp_error_is_retried(self, task, mailer_function, args, kwargs):
        with (
            patch.object(
                mailer,
                mailer_function,
                side_effect=smtplib.SMTPServerDisconnected("gone"),
            ),
            pytest.raises(Retry),
        ):
            asyncio.run(task({"job_try": 1}, *args, **kwargs))

    def test_the_last_attempt_raises_the_original_error(
        self, task, mailer_function, args, kwargs
    ):
        with (
            patch.object(
                mailer, mailer_function, side_effect=smtplib.SMTPException("down")
            ),
            pytest.raises(smtplib.SMTPException, match="down"),
        ):
            asyncio.run(task({"job_try": 4}, *args, **kwargs))

    def test_a_configuration_error_is_not_retried(
        self, task, mailer_function, args, kwargs
    ):
        with (
            patch.object(
                mailer, mailer_function, side_effect=RuntimeError("no STARTTLS")
            ),
            pytest.raises(RuntimeError, match="no STARTTLS"),
        ):
            asyncio.run(task({"job_try": 1}, *args, **kwargs))

    def test_a_call_without_job_context_counts_as_the_first_attempt(
        self, task, mailer_function, args, kwargs
    ):
        with (
            patch.object(mailer, mailer_function, side_effect=OSError("network")),
            pytest.raises(Retry) as exc_info,
        ):
            asyncio.run(task({}, *args, **kwargs))

        assert exc_info.value.defer_score == 120 * 1000

    def test_a_successful_send_neither_retries_nor_raises(
        self, task, mailer_function, args, kwargs
    ):
        with patch.object(mailer, mailer_function) as mock_send:
            asyncio.run(task({"job_try": 2}, *args, **kwargs))

        mock_send.assert_called_once()


def test_the_retry_budget_fits_into_the_workers_attempts():
    # WorkerSettings does not override arq's default.
    worker_default = inspect.signature(Worker.__init__).parameters["max_tries"].default

    assert worker_default > tasks._MAIL_MAX_TRIES
