import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.db.models.sent_email import SentEmail
from app.services import sent_email_service
from app.services.sent_email_service import SentEmailNotFoundError


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_sent_email(
    db_session: Session,
    *,
    created_at: datetime,
    updated_at: datetime,
    to: str | None = None,
    subject: str | None = None,
    mailer: str | None = "smtp",
) -> SentEmail:
    email = SentEmail(
        mail_from="noreply@example.test",
        to=to or f"{_unique('empfaenger')}@example.test",
        subject=subject or _unique("Betreff"),
        body="<p>Inhalt</p>",
        mailer=mailer,
        created_at=created_at,
        updated_at=updated_at,
    )
    db_session.add(email)
    db_session.commit()
    return email


class TestListForMonth:
    def test_filters_and_sorts_by_updated_at_not_created_at(self, db_session: Session):
        # Legacy's SentEmail::ofMonth() filters/orders by updated_at -- a
        # row created in a different month than it was last updated must
        # still show up (and sort) by updated_at.
        marker = _unique("UpdatedAtQuirk")
        older_update = _make_sent_email(
            db_session,
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
            subject=f"{marker}-alt",
        )
        newer_update = _make_sent_email(
            db_session,
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            subject=f"{marker}-neu",
        )

        result = sent_email_service.list_for_month(db_session, 2026, 3)
        ids = [item.id for item in result]

        assert older_update.id in ids
        assert newer_update.id in ids
        assert ids.index(newer_update.id) < ids.index(older_update.id)

    def test_excludes_a_different_month(self, db_session: Session):
        marker = _unique("AndererMonat")
        _make_sent_email(
            db_session,
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
            subject=marker,
        )

        result = sent_email_service.list_for_month(db_session, 2026, 5)
        assert marker not in [item.subject for item in result]

    def test_short_output_uses_updated_at_as_its_datetime_field(
        self, db_session: Session
    ):
        marker = _unique("KurzDatum")
        updated_at = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
        email = _make_sent_email(
            db_session,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=updated_at,
            subject=marker,
        )

        result = sent_email_service.list_for_month(db_session, 2026, 6)
        entry = next(item for item in result if item.id == email.id)
        assert entry.datetime.replace(tzinfo=UTC) == updated_at


class TestGet:
    def test_returns_full_detail_with_created_at_as_its_datetime_field(
        self, db_session: Session
    ):
        created_at = datetime(2026, 2, 2, 8, 0, tzinfo=UTC)
        email = _make_sent_email(
            db_session,
            created_at=created_at,
            updated_at=datetime(2026, 2, 3, 8, 0, tzinfo=UTC),
            mailer="smtp",
        )

        result = sent_email_service.get(db_session, email.id)

        assert result.id == email.id
        assert result.mailer == "smtp"
        assert result.datetime.replace(tzinfo=UTC) == created_at
        assert result.from_ == "noreply@example.test"
        assert result.body == "<p>Inhalt</p>"

    def test_raises_not_found_for_unknown_id(self, db_session: Session):
        with pytest.raises(SentEmailNotFoundError):
            sent_email_service.get(db_session, 999_999)
