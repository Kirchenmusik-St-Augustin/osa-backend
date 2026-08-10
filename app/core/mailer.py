"""Jinja2 templates + stdlib smtplib, every send logged to `sent_emails`.

Called from FastAPI `BackgroundTasks.add_task(...)` (Starlette's threadpool
for the sync function, not `asyncio.to_thread`) -- the request's own DB
session is already closed by the time a background task runs, so every
function here opens its own short-lived session via SessionLocal()
(the documented exception to the SessionLocal-outside-Depends ruff ban,
see pyproject.toml's per-file-ignores).
"""

import logging
import smtplib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings, require_setting
from app.db.database import SessionLocal
from app.db.models.sent_email import SentEmail

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
# autoescape=True: new_registration.html renders raw user-submitted
# registration fields (givenname/surname/phone) -- without escaping, a
# registration would let attacker-controlled HTML slip straight into a
# real mailbox (stored HTML-injection into the disponent's inbox).
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


def _format_short_date(value: datetime) -> str:
    # Legacy's `schedule->format('j. m. Y')` -- day/month without leading
    # zeros, same reasoning as _format_notification_timestamp (strftime's
    # non-padded %-d/%-m is a glibc-only extension, not portable). Rendered
    # in Python rather than as a Jinja template filter/global -- Jinja's
    # type stubs don't model arbitrary-callable globals cleanly, and every
    # other value already reaches these templates pre-formatted the same
    # way (see e.g. send_password_reset_email's `count=`).
    return f"{value.day}. {value.month}. {value.year}"


def _format_ymd_timestamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def _format_notification_timestamp(now: datetime) -> str:
    # Legacy's `j. n. Y, H:i` (Laravel/PHP date format) -- day/month without
    # leading zeros, unlike strftime's %d/%m.
    return f"{now.day}. {now.month}. {now.year}, {now.strftime('%H:%M')}"


def _count_recipients(value: str | None) -> int:
    if not value:
        return 0
    return len([part for part in value.split(",") if part.strip()])


@dataclass(frozen=True)
class MailKillSwitchStatus:
    """Frontend-facing kill-switch status -- see get_kill_switch_status()."""

    active: bool
    period_days: int
    threshold: int


def get_kill_switch_status(db: Session) -> MailKillSwitchStatus:
    """30-day rolling window over `sent_emails`, ported from Legacy's
    config/mail.php `limit.periodDays`/`limit.allMessagesThreshold` (30 /
    950): once the summed recipient count (to+cc+bcc) of everything sent
    in the window reaches the threshold, mail sending switches globally to
    pure logging -- never a failed request, see _send_templated_email.
    Public (unlike the private helpers around it) because it also drives
    the frontend's proactive warning icon/card (GET /auth/me,
    MessageToContactpersonView, MessageToCastView -- Schritt 7).

    Fail-safe, 1:1 Legacy's `SentEmail::ensureThresholdCompliance()`: if the
    counting query itself fails, treat mail as disabled rather than risk
    silently missing an over-threshold state."""
    settings = get_settings()
    try:
        window_start = datetime.now(UTC) - timedelta(
            days=settings.mail_kill_switch_period_days
        )
        rows = db.execute(
            select(SentEmail.to, SentEmail.cc, SentEmail.bcc).where(
                SentEmail.created_at >= window_start
            )
        ).all()
    except SQLAlchemyError:
        logger.exception("Failed to evaluate mail kill switch; treating as active.")
        return MailKillSwitchStatus(
            active=True,
            period_days=settings.mail_kill_switch_period_days,
            threshold=settings.mail_kill_switch_threshold,
        )
    total_recipients = sum(
        _count_recipients(row.to)
        + _count_recipients(row.cc)
        + _count_recipients(row.bcc)
        for row in rows
    )
    return MailKillSwitchStatus(
        active=total_recipients >= settings.mail_kill_switch_threshold,
        period_days=settings.mail_kill_switch_period_days,
        threshold=settings.mail_kill_switch_threshold,
    )


def _build_from_header() -> tuple[str, str]:
    settings = get_settings()
    return (
        settings.smtp_from_email,
        f'"{settings.smtp_from_name}" <{settings.smtp_from_email}>',
    )


def _send_message(msg: MIMEMultipart, recipients: list[str]) -> None:
    settings = get_settings()
    smtp_host = require_setting(settings.smtp_host, "SMTP_HOST")
    smtp_port = require_setting(settings.smtp_port, "SMTP_PORT")
    from_email = settings.smtp_from_email

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            if settings.smtp_user.lower() != "null":
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(from_email, recipients, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            if server.has_extn("STARTTLS"):
                server.starttls()
                server.ehlo()
            if settings.smtp_user.lower() != "null":
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(from_email, recipients, msg.as_string())


def _log_sent_email(
    to_str: str,
    subject: str,
    html_body: str,
    template_key: str,
    *,
    use_bcc: bool = False,
) -> None:
    settings = get_settings()
    try:
        db = SessionLocal()
        try:
            now = datetime.now(UTC)
            db.add(
                SentEmail(
                    mail_from=settings.smtp_from_email,
                    to=None if use_bcc else to_str,
                    bcc=to_str if use_bcc else None,
                    subject=subject,
                    body=html_body,
                    headers=template_key,
                    mailer="smtp",
                    created_at=now,
                    updated_at=now,
                )
            )
            db.commit()
        finally:
            db.close()
    except SQLAlchemyError:
        # A logging failure must never make an already-sent email look
        # like it failed -- log and move on.
        logger.exception("Failed to log sent email (template=%s)", template_key)


def _send_templated_email(
    to_emails: list[str],
    subject: str,
    template_name: str,
    template_key: str,
    *,
    use_bcc: bool = False,
    **context: object,
) -> None:
    settings = get_settings()
    to_str = ", ".join(to_emails)

    db = SessionLocal()
    try:
        kill_switch_status = get_kill_switch_status(db)
    finally:
        db.close()

    if kill_switch_status.active:
        logger.warning(
            "Mail suppressed by kill switch (>=%d recipients in the last %d days): "
            "template=%s, to=%s",
            settings.mail_kill_switch_threshold,
            settings.mail_kill_switch_period_days,
            template_key,
            to_str,
        )
        return

    html_content = _jinja_env.get_template(template_name).render(**context)
    _from_email, from_header = _build_from_header()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_header
    # BCC: every address in `to_emails` is still delivered individually via
    # the SMTP envelope (`_send_message`'s `recipients` argument controls
    # actual delivery, independent of this header) -- but the visible "To"
    # header shows only our own sender address instead of the full list, so
    # a multi-recipient blast (e.g. MessageToCast) never exposes one
    # recipient's address to another (Datenschutz, User-confirmed
    # 2026-07-31).
    msg["To"] = from_header if use_bcc else to_str
    msg["Reply-To"] = f'"{settings.smtp_from_name}" <{settings.mail_disponent}>'
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    _send_message(msg, to_emails)
    _log_sent_email(to_str, subject, html_content, template_key, use_bcc=use_bcc)


def send_verification_email(to_email: str, verify_url: str) -> None:
    now = datetime.now(UTC)
    subject = f"E-Mail-Adresse bestätigen ({_format_notification_timestamp(now)})"
    _send_templated_email(
        [to_email], subject, "verify_email.html", "verify-email", url=verify_url
    )


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    now = datetime.now(UTC)
    timestamp = _format_notification_timestamp(now)
    subject = f"Benachrichtigung zur Passwort-Rücksetzung ({timestamp})"
    settings = get_settings()
    _send_templated_email(
        [to_email],
        subject,
        "reset_password.html",
        "password-reset",
        url=reset_url,
        count=settings.password_reset_ttl_minutes,
    )


def send_new_registration_notice(
    *, surname: str, givenname: str, email: str, phone: str | None
) -> None:
    """Takes plain fields, not a User ORM instance -- this runs inside a
    BackgroundTasks callback, well after the request's DB session (and
    thus the User instance's attribute access) has already been closed."""
    settings = get_settings()
    now = datetime.now(UTC)
    timestamp = _format_ymd_timestamp(now)
    subject = f"Benachrichtigung über eine neue Registrierung ({timestamp})"
    _send_templated_email(
        [settings.mail_disponent],
        subject,
        "new_registration.html",
        "new-registration",
        surname=surname,
        givenname=givenname,
        email=email,
        phone=phone,
    )


@dataclass(frozen=True)
class BookingStatusMailEntry:
    """One row of a `send_booking_status_email` mail -- 1:1 port of
    Legacy's `booking_status.blade.php` per-BookingLog panel."""

    ordinariumwork_artist_name: str
    ordinariumwork_name: str
    schedule: datetime
    location_name: str
    location_address: str | None
    user_name: str
    booked: bool


def _booking_status_entry_context(entry: BookingStatusMailEntry) -> dict[str, object]:
    return {**asdict(entry), "schedule": _format_short_date(entry.schedule)}


def send_booking_status_email(
    to_email: str, entries: list[BookingStatusMailEntry]
) -> None:
    """Port of Legacy's `BookingStatus` mail, sent by the
    `notify_upcoming_booking_status` scheduled job (see
    app.services.booking_jobs) -- one mail per user, bundling every
    booking-log transition they haven't been notified about yet."""
    now = datetime.now(UTC)
    subject = f"Benachrichtigung Buchungs-Status ({_format_ymd_timestamp(now)})"
    _send_templated_email(
        [to_email],
        subject,
        "booking_status.html",
        "booking-status",
        entries=[_booking_status_entry_context(entry) for entry in entries],
    )


@dataclass(frozen=True)
class BookingCanceledMailEntry:
    """1:1 port of Legacy's `booked_or_standby_canceled.blade.php`
    template variables."""

    ordinariumwork_artist_name: str
    ordinariumwork_name: str
    schedule: datetime
    location_name: str
    location_address: str | None
    previous_status: int
    position_name: str


def send_booked_or_standby_canceled_email(
    to_emails: list[str], canceling_user_name: str, entry: BookingCanceledMailEntry
) -> None:
    """Port of Legacy's `BookedOrStandbyCanceled` mail -- sent synchronously
    to every `disponent` user when someone self-cancels a booking/standby
    (booking_service.change_user_request_status)."""
    now = datetime.now(UTC)
    subject = f"Eine Buchung wurde storniert! ({_format_ymd_timestamp(now)})"
    _send_templated_email(
        to_emails,
        subject,
        "booked_or_standby_canceled.html",
        "booked-or-standby-canceled",
        canceling_user_name=canceling_user_name,
        entry={**asdict(entry), "schedule": _format_short_date(entry.schedule)},
    )


def send_user_message_email(
    to_emails: list[str], sender_name: str, message: str
) -> None:
    """Port of Legacy's `UserMessage` mail/`user_message.blade.php` template
    -- previously only wired up for the unrelated Selfadmin/Support
    "message a contact person" feature (Schritt 7 scope), now reused for
    the Schritt-6 MessageToCast send bugfix (see
    booking_service.send_message_to_cast, project_osa_migration_plan
    memory). Sent via Bcc (User-confirmed 2026-07-31, Datenschutz) --
    `to_emails` here is a disponent-picked, potentially large group of
    musicians/singers who don't necessarily know each other and have no
    reason to see one another's address, unlike e.g. the small, fixed
    disponent group send_booked_or_standby_canceled_email addresses."""
    now = datetime.now(UTC)
    subject = f"Kirchenmusik-Benachrichtigung ({_format_ymd_timestamp(now)})"
    _send_templated_email(
        to_emails,
        subject,
        "user_message.html",
        "user-message",
        use_bcc=True,
        sender_name=sender_name,
        message=message,
    )
