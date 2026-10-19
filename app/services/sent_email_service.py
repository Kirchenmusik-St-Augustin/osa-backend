from typing import TYPE_CHECKING

from sqlalchemy import extract, select

from app.db.models.sent_email import SentEmail
from app.schemas.sent_email import SentEmailShortOutput, SentEmailShowOutput
from app.services.pagination import select_page

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.schemas.pagination import PagedRows, PageParams


class SentEmailNotFoundError(Exception):
    """Raised when `sent_email_id` doesn't exist."""


def list_for_month(
    db: Session, year: int, month: int, page: PageParams
) -> PagedRows[SentEmailShortOutput]:
    """Filters/sorts by `created_at`, same real-indexed-query technique as
    performance_service.list_performances_for_month()'s year/month
    extract() match. `updated_at` is deliberately not used: it gets no
    value on insert (only a real UPDATE fires the set_updated_at()
    trigger, which never happens for this write-once table) -- created_at
    is the only column guaranteed to hold this row's timestamp."""
    stmt = (
        select(SentEmail)
        .where(
            extract("year", SentEmail.created_at) == year,
            extract("month", SentEmail.created_at) == month,
        )
        .order_by(SentEmail.created_at.desc(), SentEmail.id)
    )
    return select_page(db, stmt, page).map(_to_short_output)


def _to_short_output(email: SentEmail) -> SentEmailShortOutput:
    # The month filter above never matches a row without `created_at`.
    return SentEmailShortOutput.model_validate(
        {
            "id": email.id,
            "datetime": email.created_at,
            "to": email.to,
            "subject": email.subject,
        }
    )


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
