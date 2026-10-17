import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from app.db.models.shorturl import Shorturl
from app.schemas.shorturl import ShorturlRequest
from app.services import shorturl_service

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _unique(base: str = "path") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _request(
    path: str | None = None, *, target: str = "example.org"
) -> ShorturlRequest:
    return ShorturlRequest(path=path or _unique(), target=target)


class TestNormalizeTarget:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("example.org", "https://example.org"),
            ("example.org/foo?a=1#x", "https://example.org/foo?a=1#x"),
            ("localhost:8080/x", "https://localhost:8080/x"),
            ("  example.org  ", "https://example.org"),
            ("http://example.org/foo", "http://example.org/foo"),
            ("https://example.org/foo", "https://example.org/foo"),
            ("HTTPS://Example.org", "HTTPS://Example.org"),
        ],
    )
    def test_accepts_http_addresses_and_defaults_to_https(self, given, expected):
        assert shorturl_service.normalize_target(given) == expected

    @pytest.mark.parametrize(
        "given",
        [
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd",
            "ftp://example.org/x",
            "//example.org/x",
            "https://",
            "http:///nohost",
            "   ",
        ],
    )
    def test_refuses_other_schemes_and_addresses_without_a_host(self, given):
        with pytest.raises(ValueError, match="http- und https"):
            shorturl_service.normalize_target(given)


class TestListShorturls:
    def test_returns_alphabetically_ordered(self, db_session: Session):
        marker_a, marker_z = _unique("aaa"), _unique("zzz")
        shorturl_service.create_shorturl(db_session, _request(marker_z))
        shorturl_service.create_shorturl(db_session, _request(marker_a))
        paths = [s.path for s in shorturl_service.list_shorturls(db_session)]
        assert paths.index(marker_a) < paths.index(marker_z)


class TestListShorturlsWithPrefix:
    def test_builds_urlprefix_from_settings(self, db_session: Session):
        result = shorturl_service.list_shorturls_with_prefix(db_session)
        assert result.urlprefix.startswith("https://")
        assert result.urlprefix.endswith("/")


class TestCreateShorturl:
    def test_creates_with_given_path_and_normalized_target(self, db_session: Session):
        path = _unique()
        shorturl = shorturl_service.create_shorturl(
            db_session, _request(path, target="example.org/foo")
        )
        assert shorturl.path == path
        assert shorturl.target == "https://example.org/foo"
        assert shorturl.counter == 0
        assert shorturl.latestcall_at is None

    def test_refuses_a_target_that_is_not_an_http_address(self, db_session: Session):
        with pytest.raises(shorturl_service.ShorturlValidationError) as exc_info:
            shorturl_service.create_shorturl(
                db_session, _request(target="javascript:alert(1)")
            )
        assert exc_info.value.errors == [
            ("target", "Nur http- und https-Adressen sind erlaubt.")
        ]

    def test_reports_a_taken_path_and_a_bad_target_together(self, db_session: Session):
        path = _unique()
        shorturl_service.create_shorturl(db_session, _request(path))
        with pytest.raises(shorturl_service.ShorturlValidationError) as exc_info:
            shorturl_service.create_shorturl(
                db_session, _request(path, target="ftp://example.org")
            )
        assert sorted(exc_info.value.errors) == [
            ("path", "Der Pfad ist bereits vergeben."),
            ("target", "Nur http- und https-Adressen sind erlaubt."),
        ]

    def test_duplicate_path_is_rejected(self, db_session: Session):
        path = _unique()
        shorturl_service.create_shorturl(db_session, _request(path))
        with pytest.raises(shorturl_service.ShorturlValidationError) as exc_info:
            shorturl_service.create_shorturl(db_session, _request(path))
        assert exc_info.value.errors == [("path", "Der Pfad ist bereits vergeben.")]

    def test_path_rejects_invalid_characters(self):
        with pytest.raises(ValueError, match="Erlaubt sind Buchstaben"):
            ShorturlRequest(path="bad path!", target="example.org")

    @pytest.mark.parametrize("path", ["/abc", "abc/", "//", "a//b", "/", "a/b/", "a b"])
    def test_path_rejects_leading_trailing_and_doubled_slashes(self, path):
        with pytest.raises(ValueError, match="Erlaubt sind Buchstaben"):
            ShorturlRequest(path=path, target="example.org")

    @pytest.mark.parametrize("path", ["abc", "a-b_c", "Ab1", "nested/sub", "a/b/c"])
    def test_path_accepts_slash_separated_segments(self, path):
        assert ShorturlRequest(path=path, target="example.org").path == path


class TestUpdateShorturl:
    def test_updates_path_and_target(self, db_session: Session):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        new_path = _unique("renamed")
        updated = shorturl_service.update_shorturl(
            db_session, shorturl.id, _request(new_path, target="example.org/new")
        )
        assert updated.path == new_path
        assert updated.target == "https://example.org/new"

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(shorturl_service.ShorturlNotFoundError):
            shorturl_service.update_shorturl(db_session, uuid.uuid4(), _request())

    def test_keeping_own_path_does_not_trigger_uniqueness_error(
        self, db_session: Session
    ):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        updated = shorturl_service.update_shorturl(
            db_session, shorturl.id, _request(shorturl.path, target="example.org/x")
        )
        assert updated.target == "https://example.org/x"

    def test_duplicate_path_against_another_shorturl_is_rejected(
        self, db_session: Session
    ):
        other = shorturl_service.create_shorturl(db_session, _request())
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        with pytest.raises(shorturl_service.ShorturlValidationError) as exc_info:
            shorturl_service.update_shorturl(
                db_session, shorturl.id, _request(other.path)
            )
        assert exc_info.value.errors == [("path", "Der Pfad ist bereits vergeben.")]


class TestDeleteShorturl:
    def test_deletes_without_dependency_check(self, db_session: Session):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        shorturl_service.delete_shorturl(db_session, shorturl.id)
        remaining = [s.path for s in shorturl_service.list_shorturls(db_session)]
        assert shorturl.path not in remaining

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(shorturl_service.ShorturlNotFoundError):
            shorturl_service.delete_shorturl(db_session, uuid.uuid4())


def _reload(db_session: Session, path: str):
    return next(
        s for s in shorturl_service.list_shorturls(db_session) if s.path == path
    )


class TestResolveAndRecordHit:
    def test_known_path_returns_normalized_target_and_records_hit(
        self, db_session: Session
    ):
        shorturl = shorturl_service.create_shorturl(
            db_session, _request(target="example.org/known")
        )
        target = shorturl_service.resolve_and_record_hit(db_session, shorturl.path)
        assert target == "https://example.org/known"
        reloaded = _reload(db_session, shorturl.path)
        assert reloaded.counter == 1
        assert reloaded.latestcall_at is not None

    def test_counter_increments_across_repeated_hits(self, db_session: Session):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        shorturl_service.resolve_and_record_hit(db_session, shorturl.path)
        shorturl_service.resolve_and_record_hit(db_session, shorturl.path)
        assert _reload(db_session, shorturl.path).counter == 2

    def test_hit_costs_a_single_atomic_statement(
        self, db_session: Session, count_queries
    ):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        path = shorturl.path

        with count_queries() as counter:
            shorturl_service.resolve_and_record_hit(db_session, path)

        assert counter.count == 1

    def test_a_stored_target_that_is_not_http_resolves_to_a_miss(
        self, db_session: Session
    ):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        stored = db_session.execute(
            select(Shorturl).where(Shorturl.path == shorturl.path)
        ).scalar_one()
        stored.target = "javascript:alert(1)"
        db_session.commit()

        assert (
            shorturl_service.resolve_and_record_hit(db_session, shorturl.path) is None
        )

    def test_unknown_path_returns_none(self, db_session: Session):
        assert shorturl_service.resolve_and_record_hit(db_session, _unique()) is None

    def test_listall_is_not_special_cased(self, db_session: Session):
        # Regression test for the closed security bug: with no shorturl
        # actually named "listAll", the lookup must fall through to a
        # plain miss, not any kind of dump.
        assert shorturl_service.resolve_and_record_hit(db_session, "listAll") is None
