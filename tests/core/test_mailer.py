from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core import mailer
from app.db.models.sent_email import SentEmail


@pytest.fixture(autouse=True)
def _clear_sent_emails(db_session):
    """The shared test-session DB has no per-test transaction
    rollback (unlike a per-test SAVEPOINT setup) -- kill-switch tests
    count ALL rows in `sent_emails`, so leftover rows from an earlier
    test would otherwise make these tests order-dependent."""
    db_session.query(SentEmail).delete()
    db_session.commit()
    return


def test_count_recipients_handles_none_empty_and_multiple():
    assert mailer._count_recipients(None) == 0
    assert mailer._count_recipients("") == 0
    assert mailer._count_recipients("a@example.test") == 1
    assert mailer._count_recipients("a@example.test, b@example.test") == 2


def test_format_ymd_timestamp():
    now = datetime(2026, 3, 5, 9, 7, tzinfo=UTC)
    assert mailer._format_ymd_timestamp(now) == "2026-03-05 09:07"


def test_format_short_date_has_no_leading_zeros():
    assert mailer._format_short_date(datetime(2026, 3, 5, tzinfo=UTC)) == "5. 3. 2026"


def test_format_notification_timestamp_has_no_leading_zeros():
    now = datetime(2026, 3, 5, 9, 7, tzinfo=UTC)
    assert mailer._format_notification_timestamp(now) == "5. 3. 2026, 09:07"


def test_kill_switch_inactive_with_no_prior_emails(db_session):
    status = mailer.get_kill_switch_status(db_session)
    assert status.active is False
    assert status.period_days == 30
    assert status.threshold == 950
    assert status.sent == 0


def test_kill_switch_activates_at_threshold(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAIL_KILL_SWITCH_THRESHOLD", "3")
    now = datetime.now(UTC)
    db_session.add(
        SentEmail(to="a@example.test, b@example.test, c@example.test", created_at=now)
    )
    db_session.commit()

    status = mailer.get_kill_switch_status(db_session)
    assert status.active is True
    assert status.threshold == 3
    assert status.sent == 3


def test_kill_switch_ignores_emails_outside_rolling_window(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("MAIL_KILL_SWITCH_THRESHOLD", "1")
    monkeypatch.setenv("MAIL_KILL_SWITCH_PERIOD_DAYS", "30")
    stale = datetime.now(UTC) - timedelta(days=31)
    db_session.add(SentEmail(to="a@example.test", created_at=stale))
    db_session.commit()

    assert mailer.get_kill_switch_status(db_session).active is False


def test_kill_switch_fails_safe_to_active_on_db_error():
    """1:1 Legacy's SentEmail::ensureThresholdCompliance(): a failed count
    query must never silently look like "mail sending is fine"."""
    broken_session = MagicMock()
    broken_session.execute.side_effect = SQLAlchemyError("boom")

    status = mailer.get_kill_switch_status(broken_session)

    assert status.active is True
    assert status.period_days == 30
    assert status.threshold == 950
    # Real count is unknown -- reports the threshold itself, consistent
    # with active=True (not a false "0 sent" contradicting the warning).
    assert status.sent == 950


def _make_smtp_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.test.invalid")
    monkeypatch.setenv("SMTP_PORT", "587")


def test_send_verification_email_sends_and_logs(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    _make_smtp_settings(monkeypatch)

    with patch("app.core.mailer._send_message") as mock_send:
        mailer.send_verification_email(
            "user@example.test", "https://x.test/verify?token=abc"
        )

    mock_send.assert_called_once()
    recipients = mock_send.call_args.args[1]
    assert recipients == ["user@example.test"]

    row = db_session.query(SentEmail).filter(SentEmail.headers == "verify-email").one()
    assert row.to == "user@example.test"
    assert "verify" in row.body.lower() or "bestätig" in row.body.lower()


def test_send_verification_email_subject_uses_app_timezone_not_utc(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    """Regression: email subjects must show Settings.app_timezone
    wall-clock, not UTC (previously datetime.now(UTC) leaked straight into
    the subject). fixed_local is chosen so that UTC and Vienna (CEST,
    UTC+2) render both a different hour AND a different calendar day -- a
    coincidental hour match wouldn't catch the bug."""
    _make_smtp_settings(monkeypatch)
    fixed_local = datetime(2026, 8, 15, 0, 30)  # noqa: DTZ001 -- naive Vienna wall-clock
    monkeypatch.setattr(mailer, "local_now", lambda: fixed_local)

    with patch("app.core.mailer._send_message"):
        mailer.send_verification_email("user@example.test", "https://x.test/verify")

    row = db_session.query(SentEmail).filter(SentEmail.headers == "verify-email").one()
    assert "15. 8. 2026, 00:30" in row.subject


def test_send_user_message_email_subject_uses_app_timezone_not_utc(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    """Same regression as above, covering the _format_ymd_timestamp code
    path (distinct from _format_notification_timestamp)."""
    _make_smtp_settings(monkeypatch)
    fixed_local = datetime(2026, 8, 15, 0, 30)  # noqa: DTZ001 -- naive Vienna wall-clock
    monkeypatch.setattr(mailer, "local_now", lambda: fixed_local)

    with patch("app.core.mailer._send_message"):
        mailer.send_user_message_email(["a@example.test"], "Muster, Max", "Hallo!")

    row = db_session.query(SentEmail).filter(SentEmail.headers == "user-message").one()
    assert "2026-08-15 00:30" in row.subject


def test_send_password_reset_email_body_contains_ttl_minutes(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    _make_smtp_settings(monkeypatch)

    with patch("app.core.mailer._send_message"):
        mailer.send_password_reset_email(
            "user@example.test", "https://x.test/reset?token=abc"
        )

    row = (
        db_session.query(SentEmail).filter(SentEmail.headers == "password-reset").one()
    )
    assert "60 Minuten" in row.body


def test_send_new_registration_notice_goes_to_disponent_address(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    _make_smtp_settings(monkeypatch)
    monkeypatch.setenv("MAIL_DISPONENT", "einteilung@hochamt.at")

    with patch("app.core.mailer._send_message") as mock_send:
        mailer.send_new_registration_notice(
            surname="SCHIMPL",
            givenname="Michael",
            email="m@example.test",
            phone="+43 1 234",
        )

    recipients = mock_send.call_args.args[1]
    assert recipients == ["einteilung@hochamt.at"]

    row = (
        db_session.query(SentEmail)
        .filter(SentEmail.headers == "new-registration")
        .one()
    )
    assert "SCHIMPL" in row.body
    assert "Michael" in row.body


def test_kill_switch_suppresses_send_without_logging_or_sending(
    db_session, monkeypatch: pytest.MonkeyPatch
):
    _make_smtp_settings(monkeypatch)
    monkeypatch.setenv("MAIL_KILL_SWITCH_THRESHOLD", "1")
    db_session.add(
        SentEmail(to="preexisting@example.test", created_at=datetime.now(UTC))
    )
    db_session.commit()

    rows_before = db_session.query(SentEmail).count()

    with patch("app.core.mailer._send_message") as mock_send:
        mailer.send_verification_email("user@example.test", "https://x.test/verify")

    mock_send.assert_not_called()
    assert db_session.query(SentEmail).count() == rows_before


def test_send_message_uses_ssl_for_port_465(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.invalid")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    with patch("app.core.mailer.smtplib.SMTP_SSL") as mock_ssl:
        mock_server = mock_ssl.return_value.__enter__.return_value
        mailer._send_message(MagicMock(), ["a@example.test"])

    mock_ssl.assert_called_once_with("smtp.test.invalid", 465)
    mock_server.login.assert_called_once_with("user", "secret")


def test_send_message_uses_starttls_when_available(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.invalid")
    monkeypatch.setenv("SMTP_PORT", "587")

    with patch("app.core.mailer.smtplib.SMTP") as mock_smtp:
        mock_server = mock_smtp.return_value.__enter__.return_value
        mock_server.has_extn.return_value = True
        mailer._send_message(MagicMock(), ["a@example.test"])

    mock_server.starttls.assert_called_once()
    assert mock_server.ehlo.call_count == 2


def test_send_message_skips_starttls_when_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.invalid")
    monkeypatch.setenv("SMTP_PORT", "587")

    with patch("app.core.mailer.smtplib.SMTP") as mock_smtp:
        mock_server = mock_smtp.return_value.__enter__.return_value
        mock_server.has_extn.return_value = False
        mailer._send_message(MagicMock(), ["a@example.test"])

    mock_server.starttls.assert_not_called()
    assert mock_server.ehlo.call_count == 1


def test_send_message_skips_login_when_user_is_null_sentinel(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SMTP_HOST", "smtp.test.invalid")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "null")

    with patch("app.core.mailer.smtplib.SMTP") as mock_smtp:
        mock_server = mock_smtp.return_value.__enter__.return_value
        mock_server.has_extn.return_value = False
        mailer._send_message(MagicMock(), ["a@example.test"])

    mock_server.login.assert_not_called()


def test_send_message_requires_smtp_host_and_port(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)

    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        mailer._send_message(MagicMock(), ["a@example.test"])


def test_log_sent_email_swallows_db_errors(caplog):
    with patch("app.core.mailer.SessionLocal") as mock_session_local:
        mock_session_local.return_value.commit.side_effect = SQLAlchemyError("boom")
        mailer._log_sent_email("a@example.test", "Subject", "<p>hi</p>", "test-key")

    assert "Failed to log sent email" in caplog.text


def _booking_status_entry(**overrides: object) -> mailer.BookingStatusMailEntry:
    defaults: dict[str, object] = {
        "ordinariumwork_artist_name": "MOZART Wolfgang Amadé",
        "ordinariumwork_name": "Krönungsmesse",
        "schedule": datetime(2026, 8, 9, 11, 0, tzinfo=UTC),
        "location_name": "Augustinerkirche",
        "location_address": "Augustinerstraße 3",
        "user_name": "Muster, Max",
        "booked": True,
    }
    defaults.update(overrides)
    return mailer.BookingStatusMailEntry(**defaults)  # type: ignore[arg-type]


class TestSendBookingStatusEmail:
    def test_sends_and_logs_with_singular_intro_for_one_entry(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        _make_smtp_settings(monkeypatch)
        with patch("app.core.mailer._send_message") as mock_send:
            mailer.send_booking_status_email(
                "user@example.test", [_booking_status_entry()]
            )

        recipients = mock_send.call_args.args[1]
        assert recipients == ["user@example.test"]
        row = (
            db_session.query(SentEmail)
            .filter(SentEmail.headers == "booking-status")
            .one()
        )
        assert "die folgende Aufführung" in row.body
        assert "gebucht" in row.body

    def test_plural_intro_for_multiple_entries(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        _make_smtp_settings(monkeypatch)
        with patch("app.core.mailer._send_message"):
            mailer.send_booking_status_email(
                "user@example.test",
                [_booking_status_entry(), _booking_status_entry(booked=False)],
            )

        row = (
            db_session.query(SentEmail)
            .filter(SentEmail.headers == "booking-status")
            .one()
        )
        assert "die folgenden Aufführungen" in row.body
        assert "nicht gebucht" in row.body


class TestSendBookedOrStandbyCanceledEmail:
    def test_sends_to_all_disponent_addresses(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        _make_smtp_settings(monkeypatch)
        entry = mailer.BookingCanceledMailEntry(
            ordinariumwork_artist_name="HAYDN Joseph",
            ordinariumwork_name="Nelsonmesse",
            schedule=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
            location_name="Stephansdom",
            location_address=None,
            previous_status=4,
            position_name="Violine 1",
        )
        with patch("app.core.mailer._send_message") as mock_send:
            mailer.send_booked_or_standby_canceled_email(
                ["disponent1@example.test", "disponent2@example.test"],
                "Muster, Max",
                entry,
            )

        recipients = mock_send.call_args.args[1]
        assert recipients == ["disponent1@example.test", "disponent2@example.test"]
        row = (
            db_session.query(SentEmail)
            .filter(SentEmail.headers == "booked-or-standby-canceled")
            .one()
        )
        assert "Muster, Max hat soeben folgende Buchung storniert" in row.body
        assert "Gebucht" in row.body
        assert "Violine 1" in row.body


class TestSendUserMessageEmail:
    def test_sends_and_logs_message_body(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        _make_smtp_settings(monkeypatch)
        with patch("app.core.mailer._send_message") as mock_send:
            mailer.send_user_message_email(
                ["a@example.test", "b@example.test"], "Muster, Max", "Hallo zusammen!"
            )

        recipients = mock_send.call_args.args[1]
        assert recipients == ["a@example.test", "b@example.test"]
        row = (
            db_session.query(SentEmail)
            .filter(SentEmail.headers == "user-message")
            .one()
        )
        assert "Muster, Max hat folgende Nachricht geschickt" in row.body
        assert "Hallo zusammen!" in row.body

    def test_sends_via_bcc_so_recipients_never_see_each_other(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ):
        """Datenschutz (User-confirmed 2026-07-31): a MessageToCast blast
        can go out to dozens of musicians/singers who don't know each
        other -- none of their addresses may appear in a header any of
        them can see, even though every one of them still gets delivered
        the message via the SMTP envelope (`_send_message`'s `recipients`
        argument, asserted above/unaffected by this)."""
        _make_smtp_settings(monkeypatch)
        with patch("app.core.mailer._send_message") as mock_send:
            mailer.send_user_message_email(
                ["a@example.test", "b@example.test"], "Muster, Max", "Hallo zusammen!"
            )

        msg = mock_send.call_args.args[0]
        assert "a@example.test" not in msg["To"]
        assert "b@example.test" not in msg["To"]

        row = (
            db_session.query(SentEmail)
            .filter(SentEmail.headers == "user-message")
            .one()
        )
        assert row.to is None
        assert row.bcc == "a@example.test, b@example.test"

    def test_message_html_is_escaped(self, db_session, monkeypatch: pytest.MonkeyPatch):
        _make_smtp_settings(monkeypatch)
        with patch("app.core.mailer._send_message"):
            mailer.send_user_message_email(
                ["a@example.test"], "Angreifer", "<script>alert(1)</script>"
            )

        row = (
            db_session.query(SentEmail)
            .filter(SentEmail.headers == "user-message")
            .one()
        )
        assert "<script>" not in row.body
        assert "&lt;script&gt;" in row.body
