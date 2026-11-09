import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from app.schemas.pagination import MAX_PAGE_SIZE, PageParams
from app.services import sent_email_service
from app.services.sent_email_service import SentEmailNotFoundError
from tests.sent_emails import sent_email
from tests.sql_capture import recorded_statements

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.db.models.sent_email import SentEmail


_ALL_ROWS = PageParams(limit=MAX_PAGE_SIZE, offset=0)


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
    email = sent_email(
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
    def test_filters_and_sorts_by_created_at_not_updated_at(self, db_session: Session):
        # updated_at gets no value on insert (a real UPDATE never happens for
        # this write-once table) -- a row updated_at-stamped into a
        # different month than it was created must still show up (and
        # sort) by created_at, the only column reliably populated.
        older = _make_sent_email(
            db_session,
            created_at=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
            updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            subject=_unique("CreatedAtQuirk-alt"),
        )
        newer = _make_sent_email(
            db_session,
            created_at=datetime(2026, 3, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            subject=_unique("CreatedAtQuirk-neu"),
        )

        result = sent_email_service.list_for_month(db_session, 2026, 3, _ALL_ROWS).rows
        ids = [item.id for item in result]

        assert older.id in ids
        assert newer.id in ids
        assert ids.index(newer.id) < ids.index(older.id)

    def test_excludes_a_different_month(self, db_session: Session):
        marker = _unique("AndererMonat")
        _make_sent_email(
            db_session,
            created_at=datetime(2026, 4, 1, tzinfo=UTC),
            updated_at=datetime(2026, 4, 1, tzinfo=UTC),
            subject=marker,
        )

        result = sent_email_service.list_for_month(db_session, 2026, 5, _ALL_ROWS).rows
        assert marker not in [item.subject for item in result]

    def test_excludes_the_same_month_of_a_different_year(self, db_session: Session):
        marker = _unique("AndresJahr")
        other_year = datetime(2027, 3, 15, tzinfo=UTC)
        _make_sent_email(
            db_session, created_at=other_year, updated_at=other_year, subject=marker
        )

        result = sent_email_service.list_for_month(db_session, 2026, 3, _ALL_ROWS)

        assert marker not in [item.subject for item in result.rows]
        assert marker in [
            item.subject
            for item in sent_email_service.list_for_month(
                db_session, 2027, 3, _ALL_ROWS
            ).rows
        ]

    def test_short_output_uses_created_at_as_its_datetime_field(
        self, db_session: Session
    ):
        marker = _unique("KurzDatum")
        created_at = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
        email = _make_sent_email(
            db_session,
            created_at=created_at,
            updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            subject=marker,
        )

        result = sent_email_service.list_for_month(db_session, 2026, 6, _ALL_ROWS).rows
        entry = next(item for item in result if item.id == email.id)
        assert entry.datetime.replace(tzinfo=UTC) == created_at


class TestMonthBoundaryIsLocal:
    def test_a_mail_just_after_local_midnight_belongs_to_the_new_month(
        self, db_session: Session
    ):
        # 23:30 UTC on 28 February is 00:30 on 1 March in Vienna.
        stamp = datetime(2031, 2, 28, 23, 30, tzinfo=UTC)
        email = _make_sent_email(db_session, created_at=stamp, updated_at=stamp)

        february = sent_email_service.list_for_month(db_session, 2031, 2, _ALL_ROWS)
        march = sent_email_service.list_for_month(db_session, 2031, 3, _ALL_ROWS)

        assert email.id not in [item.id for item in february.rows]
        assert email.id in [item.id for item in march.rows]

    def test_a_mail_just_before_local_midnight_stays_in_the_old_month(
        self, db_session: Session
    ):
        # 22:30 UTC on 31 March is 00:30 on 1 April in summer time; 21:30 UTC
        # is still 23:30 on 31 March.
        late = datetime(2031, 3, 31, 21, 30, tzinfo=UTC)
        early = datetime(2031, 3, 31, 22, 30, tzinfo=UTC)
        in_march = _make_sent_email(db_session, created_at=late, updated_at=late)
        in_april = _make_sent_email(db_session, created_at=early, updated_at=early)

        march = sent_email_service.list_for_month(db_session, 2031, 3, _ALL_ROWS)
        april = sent_email_service.list_for_month(db_session, 2031, 4, _ALL_ROWS)

        assert in_march.id in [item.id for item in march.rows]
        assert in_april.id not in [item.id for item in march.rows]
        assert in_april.id in [item.id for item in april.rows]

    def test_a_mail_at_the_exact_start_instant_of_a_month_belongs_to_that_month(
        self, db_session: Session
    ):
        # Local midnight of 1 March 2031 (UTC+1) and of 1 April 2031 (UTC+2).
        march_start = datetime(2031, 2, 28, 23, 0, tzinfo=UTC)
        april_start = datetime(2031, 3, 31, 22, 0, tzinfo=UTC)
        first = _make_sent_email(
            db_session, created_at=march_start, updated_at=march_start
        )
        second = _make_sent_email(
            db_session, created_at=april_start, updated_at=april_start
        )

        march = sent_email_service.list_for_month(db_session, 2031, 3, _ALL_ROWS)
        april = sent_email_service.list_for_month(db_session, 2031, 4, _ALL_ROWS)

        march_ids = [item.id for item in march.rows]
        april_ids = [item.id for item in april.rows]
        assert first.id in march_ids
        assert second.id not in march_ids
        assert second.id in april_ids
        assert first.id not in april_ids

    def test_the_month_filter_is_a_range_on_created_at(self, db_session: Session):
        with recorded_statements() as statements:
            sent_email_service.list_for_month(db_session, 2031, 3, _ALL_ROWS)

        listing = next(
            s for s in statements if "FROM sent_emails" in s and "LIMIT" in s
        )
        assert "EXTRACT" not in listing.upper()
        assert "sent_emails.created_at >=" in listing
        assert "sent_emails.created_at <" in listing


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
            sent_email_service.get(db_session, uuid.uuid4())
