import json
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.client_user_agent import ClientUserAgent
from app.db.models.request_log import RequestLog
from app.services import request_log_service
from app.services.request_log_service import (
    RequestLogNotFoundError,
    RequestLogUserNotFoundError,
)


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_entry(
    db_session: Session,
    *,
    user_id: int | None,
    created_at: datetime,
    request_method: str = "GET",
    request_path: str | None = None,
    client_user_agent_id: int | None = None,
) -> RequestLog:
    entry = RequestLog(
        client_ip="127.0.0.1",
        client_ips="[]",
        client_user_agent_id=client_user_agent_id,
        user_id=user_id,
        request_method=request_method,
        request_path=request_path or _unique("/some/path"),
        request_input="{}",
        response_status=200,
        response_content="null",
        memory_usage=1,
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


class TestRedact:
    def test_masks_a_flat_password_field(self):
        result = request_log_service.redact(
            {"username": "max@example.test", "password": "hunter2"}
        )
        assert result == {"username": "max@example.test", "password": "__removed__"}

    def test_masks_access_and_refresh_tokens_in_a_response_body(self):
        # The security-hardening case this whole redaction step exists for
        # -- our JWT login response body carries the access_token directly.
        result = request_log_service.redact(
            {"access_token": "eyJhbGciOi...", "token_type": "bearer"}
        )
        assert result == {"access_token": "__removed__", "token_type": "bearer"}

    def test_matches_keys_case_insensitively(self):
        result = request_log_service.redact({"Authorization": "Bearer xyz"})
        assert result == {"Authorization": "__removed__"}

    def test_masks_nested_dicts_and_lists(self):
        result = request_log_service.redact(
            {
                "user": {"email": "a@b.test", "current_password": "old"},
                "items": [{"secret": "s1"}, {"secret": "s2"}],
            }
        )
        assert result == {
            "user": {"email": "a@b.test", "current_password": "__removed__"},
            "items": [{"secret": "__removed__"}, {"secret": "__removed__"}],
        }

    def test_leaves_non_matching_values_untouched(self):
        assert request_log_service.redact({"givenname": "Max"}) == {"givenname": "Max"}
        assert request_log_service.redact(None) is None
        assert request_log_service.redact([1, 2, 3]) == [1, 2, 3]

    def test_does_not_mutate_the_input(self):
        original = {"password": "hunter2"}
        request_log_service.redact(original)
        assert original == {"password": "hunter2"}


class TestShouldSkip:
    def test_skips_the_liveness_check(self):
        assert request_log_service.should_skip("/", skip_header_present=False) is True

    def test_skips_when_the_skip_header_is_present(self):
        assert (
            request_log_service.should_skip("/some/path", skip_header_present=True)
            is True
        )

    def test_logs_a_regular_path_by_default(self):
        assert (
            request_log_service.should_skip("/auth/login", skip_header_present=False)
            is False
        )


class TestRecordRequest:
    def test_writes_a_row_with_redacted_request_and_response(self, db_session: Session):
        # A unique path, not the literal "/auth/login" -- this call is the
        # only thing writing to request_logs within this test's own
        # per-test transaction (see conftest.py's SessionLocal patch for
        # request_logging.py's middleware too), so a fixed literal would
        # work today, but scalar_one() below stays honestly unambiguous
        # without relying on that.
        request_path = _unique("/auth/login")
        request_log_service.record_request(
            db_session,
            client_ip="127.0.0.1",
            client_ips=["127.0.0.1"],
            user_id=None,
            user_agent_string="pytest-agent/1.0",
            request_method="POST",
            request_path=request_path,
            request_input={"username": "max@example.test", "password": "hunter2"},
            response_status=200,
            response_content={"access_token": "secret-token", "token_type": "bearer"},
            memory_usage=12345,
        )

        row = db_session.execute(
            select(RequestLog).where(RequestLog.request_path == request_path)
        ).scalar_one()
        assert row.client_ip == "127.0.0.1"
        assert json.loads(row.client_ips) == ["127.0.0.1"]
        assert row.response_status == 200
        assert json.loads(row.request_input) == {
            "username": "max@example.test",
            "password": "__removed__",
        }
        assert json.loads(row.response_content) == {
            "access_token": "__removed__",
            "token_type": "bearer",
        }

    def test_dedupes_client_user_agent_by_exact_string(self, db_session: Session):
        for _ in range(2):
            request_log_service.record_request(
                db_session,
                client_ip="127.0.0.1",
                client_ips=["127.0.0.1"],
                user_id=None,
                user_agent_string="shared-agent-string/1.0",
                request_method="GET",
                request_path="/some/path",
                request_input={},
                response_status=200,
                response_content=None,
                memory_usage=1,
            )

        matches = (
            db_session.execute(
                select(ClientUserAgent).where(
                    ClientUserAgent.string == "shared-agent-string/1.0"
                )
            )
            .scalars()
            .all()
        )
        assert len(matches) == 1

    def test_leaves_client_user_agent_id_null_without_a_user_agent_header(
        self, db_session: Session
    ):
        request_log_service.record_request(
            db_session,
            client_ip="127.0.0.1",
            client_ips=["127.0.0.1"],
            user_id=None,
            user_agent_string=None,
            request_method="GET",
            request_path="/no-agent-path",
            request_input={},
            response_status=200,
            response_content=None,
            memory_usage=1,
        )

        row = db_session.execute(
            select(RequestLog).where(RequestLog.request_path == "/no-agent-path")
        ).scalar_one()
        assert row.client_user_agent_id is None


class TestListDaysWithUsersForMonth:
    def test_returns_a_day_group_containing_the_active_user(
        self, db_session: Session, make_user
    ):
        user = make_user()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)

        day_group = next(g for g in result if g.day == date(2026, 6, 10))
        assert user.id in [item.id for item in day_group.users]

    def test_excludes_a_user_with_only_entries_in_a_different_month(
        self, db_session: Session, make_user
    ):
        user = make_user()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 5, 10, 9, 0, tzinfo=UTC),
        )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)

        assert all(user.id not in [item.id for item in g.users] for g in result)

    def test_includes_a_soft_deleted_user(self, db_session: Session, make_user):
        # Legacy's index() branch explicitly uses withTrashed() -- a user
        # who got soft-deleted after the fact must still show up here.
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)

        day_group = next(g for g in result if g.day == date(2026, 6, 10))
        assert user.id in [item.id for item in day_group.users]

    def test_separates_two_users_active_on_different_days_into_two_groups(
        self, db_session: Session, make_user
    ):
        first = make_user()
        second = make_user()
        _make_entry(
            db_session,
            user_id=first.id,
            created_at=datetime(2026, 6, 5, 9, 0, tzinfo=UTC),
        )
        _make_entry(
            db_session,
            user_id=second.id,
            created_at=datetime(2026, 6, 15, 9, 0, tzinfo=UTC),
        )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)

        day_5 = next(g for g in result if g.day == date(2026, 6, 5))
        day_15 = next(g for g in result if g.day == date(2026, 6, 15))
        assert first.id in [u.id for u in day_5.users]
        assert first.id not in [u.id for u in day_15.users]
        assert second.id in [u.id for u in day_15.users]
        assert second.id not in [u.id for u in day_5.users]

    def test_includes_a_user_active_on_multiple_days_in_each_relevant_group(
        self, db_session: Session, make_user
    ):
        user = make_user()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 3, 9, 0, tzinfo=UTC),
        )
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 20, 9, 0, tzinfo=UTC),
        )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)

        day_3 = next(g for g in result if g.day == date(2026, 6, 3))
        day_20 = next(g for g in result if g.day == date(2026, 6, 20))
        assert user.id in [u.id for u in day_3.users]
        assert user.id in [u.id for u in day_20.users]

    def test_sorted_by_surname_then_givenname_within_a_day(
        self, db_session: Session, make_user
    ):
        # Legacy's `User` model carries a global `OrderBySurnameGivenname`
        # scope applied to EVERY User query, including this whereIn lookup.
        # Surnames prefixed via _unique() -- `users` has a real UNIQUE
        # (surname, givenname) constraint, and the shared test-session
        # DB isn't rolled back between tests/files.
        third = make_user()
        third.surname, third.givenname = _unique("ZEHETNER"), "Anna"
        first = make_user()
        first.surname, first.givenname = _unique("AAAMSTETTER"), "Bernd"
        db_session.commit()
        for user in (third, first):
            _make_entry(
                db_session,
                user_id=user.id,
                created_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
            )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)
        day_group = next(g for g in result if g.day == date(2026, 6, 10))
        ids = [item.id for item in day_group.users if item.id in (first.id, third.id)]

        assert ids == [first.id, third.id]

    def test_days_are_sorted_newest_first(self, db_session: Session, make_user):
        for day in (3, 15, 27):
            _make_entry(
                db_session,
                user_id=make_user().id,
                created_at=datetime(2026, 6, day, 9, 0, tzinfo=UTC),
            )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)
        days = [g.day for g in result]

        assert days == sorted(days, reverse=True)

    def test_label_is_space_separated_without_a_comma(
        self, db_session: Session, make_user
    ):
        # Deliberate Legacy inconsistency vs. list_entries_for_user_day()'s
        # comma-format `username` below: Index.vue's pug template renders
        # the raw `{{ user.surname }} {{ user.givenname }}` fields directly,
        # not the comma-format `name` accessor.
        user = make_user()
        user.surname, user.givenname = _unique("ZWICKENPFLUG"), "Doris"
        db_session.commit()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        )

        result = request_log_service.list_days_with_users_for_month(db_session, 2026, 6)
        day_group = next(g for g in result if g.day == date(2026, 6, 10))

        label = next(item.label for item in day_group.users if item.id == user.id)
        assert label == f"{user.surname} Doris"
        assert "," not in label

    def test_buckets_the_last_day_of_the_month_by_vienna_calendar_day_not_utc(
        self, db_session: Session, make_user
    ):
        # 22:05 UTC on Aug 31 is 00:05 CEST on Sep 1 in Vienna (UTC+2 in
        # August) -- must NOT appear in August's result at all; falls into
        # September's local calendar day, cleanly excluded by
        # month_end_utc == local_day_bounds_utc(date(2026, 9, 1))[0].
        user = make_user()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 8, 31, 22, 5, tzinfo=UTC),
        )

        august_result = request_log_service.list_days_with_users_for_month(
            db_session, 2026, 8
        )
        september_result = request_log_service.list_days_with_users_for_month(
            db_session, 2026, 9
        )

        assert all(user.id not in [u.id for u in g.users] for g in august_result)
        september_day_group = next(
            g for g in september_result if g.day == date(2026, 9, 1)
        )
        assert user.id in [u.id for u in september_day_group.users]

    def test_handles_a_december_to_january_year_rollover(
        self, db_session: Session, make_user
    ):
        user = make_user()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 12, 31, 12, 0, tzinfo=UTC),
        )

        result = request_log_service.list_days_with_users_for_month(
            db_session, 2026, 12
        )

        day_group = next(g for g in result if g.day == date(2026, 12, 31))
        assert user.id in [u.id for u in day_group.users]


class TestListEntriesForUserDay:
    def test_returns_entries_sorted_ascending_by_created_at(
        self, db_session: Session, make_user
    ):
        user = make_user()
        later = _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 10, 12, 0, tzinfo=UTC),
        )
        earlier = _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 10, 8, 0, tzinfo=UTC),
        )

        result = request_log_service.list_entries_for_user_day(
            db_session, user.id, date(2026, 6, 10)
        )

        assert [entry.id for entry in result.entries] == [earlier.id, later.id]

    def test_excludes_an_entry_on_a_different_day(self, db_session: Session, make_user):
        user = make_user()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 11, 8, 0, tzinfo=UTC),
        )

        result = request_log_service.list_entries_for_user_day(
            db_session, user.id, date(2026, 6, 10)
        )

        assert result.entries == []

    def test_username_uses_label_for_name(self, db_session: Session, make_user):
        user = make_user()
        user.surname, user.givenname = "SCHINDLER", "Margot"
        db_session.commit()

        result = request_log_service.list_entries_for_user_day(
            db_session, user.id, date(2026, 6, 10)
        )

        assert result.username == "SCHINDLER, Margot"

    def test_finds_a_soft_deleted_user(self, db_session: Session, make_user):
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        result = request_log_service.list_entries_for_user_day(
            db_session, user.id, date(2026, 6, 10)
        )

        assert result.entries == []

    def test_raises_not_found_for_a_nonexistent_user(self, db_session: Session):
        with pytest.raises(RequestLogUserNotFoundError):
            request_log_service.list_entries_for_user_day(
                db_session, 999_999, date(2026, 6, 10)
            )

    def test_buckets_an_entry_by_vienna_calendar_day_not_utc_calendar_day(
        self, db_session: Session, make_user
    ):
        # 22:05 UTC on Aug 12 is 00:05 CEST on Aug 13 in Vienna (UTC+2 in
        # August) -- regression guard for local_day_bounds_utc() bucketing
        # by the LOCAL calendar day, not the raw UTC calendar day.
        user = make_user()
        _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 8, 12, 22, 5, tzinfo=UTC),
        )

        aug_12 = request_log_service.list_entries_for_user_day(
            db_session, user.id, date(2026, 8, 12)
        )
        aug_13 = request_log_service.list_entries_for_user_day(
            db_session, user.id, date(2026, 8, 13)
        )

        assert aug_12.entries == []
        assert len(aug_13.entries) == 1


class TestGet:
    def test_returns_full_detail(self, db_session: Session, make_user):
        user = make_user()
        entry = _make_entry(
            db_session,
            user_id=user.id,
            created_at=datetime(2026, 6, 10, tzinfo=UTC),
            request_method="POST",
            request_path="/auth/login",
        )

        result = request_log_service.get(db_session, entry.id)

        assert result.id == entry.id
        assert result.request_method == "POST"
        assert result.request_path == "/auth/login"
        assert result.user_id == user.id
        assert result.user_name == f"{user.surname}, {user.givenname}"

    def test_user_name_is_none_for_a_soft_deleted_user(
        self, db_session: Session, make_user
    ):
        # Deliberate asymmetry vs. list_days_with_users_for_month/
        # list_entries_for_user_day: Legacy's Show resource does a PLAIN
        # (non-withTrashed) User::find().
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()
        entry = _make_entry(
            db_session, user_id=user.id, created_at=datetime(2026, 6, 10, tzinfo=UTC)
        )

        result = request_log_service.get(db_session, entry.id)

        assert result.user_name is None

    def test_user_name_is_none_for_a_guest_request(self, db_session: Session):
        entry = _make_entry(
            db_session, user_id=None, created_at=datetime(2026, 6, 10, tzinfo=UTC)
        )

        result = request_log_service.get(db_session, entry.id)

        assert result.user_id is None
        assert result.user_name is None

    def test_deserializes_json_columns(self, db_session: Session):
        entry = RequestLog(
            client_ip="203.0.113.1",
            client_ips='["203.0.113.1", "198.51.100.1"]',
            client_user_agent_id=None,
            user_id=None,
            request_method="GET",
            request_path="/some/path",
            request_input='{"foo": "bar"}',
            response_status=200,
            response_content='{"baz": 1}',
            memory_usage=42,
            created_at=datetime(2026, 6, 10, tzinfo=UTC),
            updated_at=datetime(2026, 6, 10, tzinfo=UTC),
        )
        db_session.add(entry)
        db_session.commit()

        result = request_log_service.get(db_session, entry.id)

        assert result.client_ips == ["203.0.113.1", "198.51.100.1"]
        assert result.request_input == {"foo": "bar"}
        assert result.response_content == {"baz": 1}
        assert result.memory_usage == 42

    def test_raises_not_found_for_unknown_id(self, db_session: Session):
        with pytest.raises(RequestLogNotFoundError):
            request_log_service.get(db_session, 999_999)
