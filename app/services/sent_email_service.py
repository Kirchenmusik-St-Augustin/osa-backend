import uuid

from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app.db.models.sent_email import SentEmail
from app.schemas.sent_email import SentEmailShortOutput, SentEmailShowOutput


class SentEmailNotFoundError(Exception):
    """Raised when `sent_email_id` doesn't exist."""


def list_for_month(db: Session, year: int, month: int) -> list[SentEmailShortOutput]:
    """Filters/sorts by `created_at`, same real-indexed-query technique as
    performance_service.list_performances_for_month()'s year/month
    extract() match. Legacy's `SentEmail::ofMonth()` used `updated_at`
    instead -- harmless there since Laravel stamps both columns
    identically on create() and a sent-email row is never updated
    afterwards, so the two were always equal. As of the audit-trigger
    hardening slice (2026-09), `updated_at` no longer gets a value on
    insert (only a real UPDATE fires the set_updated_at() trigger, which
    never happens for this write-once table) -- created_at is the only
    column guaranteed to hold this row's timestamp."""
    emails = (
        db.execute(
            select(SentEmail)
            .where(
                extract("year", SentEmail.created_at) == year,
                extract("month", SentEmail.created_at) == month,
            )
            .order_by(SentEmail.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        SentEmailShortOutput(
            id=email.id, datetime=email.created_at, to=email.to, subject=email.subject
        )
        for email in emails
        if email.created_at is not None
    ]


def get(db: Session, sent_email_id: uuid.UUID) -> SentEmailShowOutput:
    email = db.execute(
        select(SentEmail).where(SentEmail.id == sent_email_id)
    ).scalar_one_or_none()
    if email is None or email.created_at is None:
        raise SentEmailNotFoundError
    return SentEmailShowOutput.model_validate(
        {
            "id": email.id,
            "mailer": email.mailer,
            "datetime": email.created_at,
            "from": email.mail_from,
            "to": email.to,
            "cc": email.cc,
            "bcc": email.bcc,
            "subject": email.subject,
            "body": email.body,
        }
    )
