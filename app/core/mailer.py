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


def _format_registration_timestamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def _format_notification_timestamp(now: datetime) -> str:
    # Legacy's `j. n. Y, H:i` (Laravel/PHP date format) -- day/month without
    # leading zeros, unlike strftime's %d/%m.
    return f"{now.day}. {now.month}. {now.year}, {now.strftime('%H:%M')}"


def _count_recipients(value: str | None) -> int:
    if not value:
        return 0
    return len([part for part in value.split(",") if part.strip()])


def _is_kill_switch_active(db: Session) -> bool:
    """30-day rolling window over `sent_emails`, ported from Legacy's
    config/mail.php `limit.periodDays`/`limit.allMessagesThreshold` (30 /
    950): once the summed recipient count (to+cc+bcc) of everything sent
    in the window reaches the threshold, mail sending switches globally to
    pure logging -- never a failed request, see _send_templated_email."""
    settings = get_settings()
    window_start = datetime.now(UTC) - timedelta(
        days=settings.mail_kill_switch_period_days
    )
    rows = db.execute(
        select(SentEmail.to, SentEmail.cc, SentEmail.bcc).where(
            SentEmail.created_at >= window_start
        )
    ).all()
    total_recipients = sum(
        _count_recipients(row.to)
        + _count_recipients(row.cc)
        + _count_recipients(row.bcc)
        for row in rows
    )
    return total_recipients >= settings.mail_kill_switch_threshold


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
    to_str: str, subject: str, html_body: str, template_key: str
) -> None:
    settings = get_settings()
    try:
        db = SessionLocal()
        try:
            now = datetime.now(UTC)
            db.add(
                SentEmail(
                    mail_from=settings.smtp_from_email,
                    to=to_str,
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
    **context: object,
) -> None:
    settings = get_settings()
    to_str = ", ".join(to_emails)

    db = SessionLocal()
    try:
        kill_switch_active = _is_kill_switch_active(db)
    finally:
        db.close()

    if kill_switch_active:
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
    msg["To"] = to_str
    msg["Reply-To"] = f'"{settings.smtp_from_name}" <{settings.mail_disponent}>'
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    _send_message(msg, to_emails)
    _log_sent_email(to_str, subject, html_content, template_key)


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
    timestamp = _format_registration_timestamp(now)
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
