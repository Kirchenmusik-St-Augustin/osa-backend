import asyncio
from datetime import datetime
from unittest.mock import patch

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
