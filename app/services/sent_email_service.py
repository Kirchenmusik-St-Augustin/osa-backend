from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.sent_email import SentEmail
from app.schemas.sent_email import SentEmailShortOutput, SentEmailShowOutput


class SentEmailNotFoundError(Exception):
    """Raised when `sent_email_id` doesn't exist."""


def list_for_month(db: Session, year: int, month: int) -> list[SentEmailShortOutput]:
    """1:1 Legacy's `SentEmail::ofMonth()` -- filters/sorts by `updated_at`
    (not `created_at`), same real-indexed-query technique as
    performance_service.list_performances_for_month()'s strftime match."""
    month_str = f"{year:04d}-{month:02d}"
    emails = (
        db.execute(
            select(SentEmail)
            .where(func.strftime("%Y-%m", SentEmail.updated_at) == month_str)
            .order_by(SentEmail.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        SentEmailShortOutput(
            id=email.id, datetime=email.updated_at, to=email.to, subject=email.subject
        )
        for email in emails
        if email.updated_at is not None
    ]


def get(db: Session, sent_email_id: int) -> SentEmailShowOutput:
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
