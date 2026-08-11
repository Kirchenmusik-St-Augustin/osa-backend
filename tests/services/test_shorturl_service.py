import uuid

import pytest
from sqlalchemy.orm import Session

from app.schemas.shorturl import ShorturlRequest
from app.services import shorturl_service


def _unique(base: str = "path") -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _request(
    path: str | None = None, *, target: str = "example.org"
) -> ShorturlRequest:
    return ShorturlRequest(path=path or _unique(), target=target)


class TestEnsureScheme:
    def test_prepends_http_when_scheme_missing(self):
        assert shorturl_service.ensure_scheme("example.org") == "http://example.org"

    def test_leaves_http_scheme_untouched(self):
        url = "http://example.org/foo"
        assert shorturl_service.ensure_scheme(url) == url

    def test_leaves_https_scheme_untouched(self):
        url = "https://example.org/foo"
        assert shorturl_service.ensure_scheme(url) == url


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
        assert shorturl.target == "http://example.org/foo"
        assert shorturl.counter == 0
        assert shorturl.latestcall_at is None

    def test_strips_only_leading_slashes(self, db_session: Session):
        # 1:1 Legacy's ltrim($validated['path'], '/') -- leading only, not
        # trailing/embedded.
        shorturl = shorturl_service.create_shorturl(
            db_session, _request(f"///{_unique('nested/sub')}/")
        )
        assert not shorturl.path.startswith("/")
        assert shorturl.path.endswith("/")

    def test_duplicate_path_is_rejected(self, db_session: Session):
        path = _unique()
        shorturl_service.create_shorturl(db_session, _request(path))
        with pytest.raises(shorturl_service.ShorturlValidationError) as exc_info:
            shorturl_service.create_shorturl(db_session, _request(path))
        assert exc_info.value.errors == [("path", "Der Pfad ist bereits vergeben.")]

    def test_path_pattern_rejects_invalid_characters(self):
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(pattern=...)
            ShorturlRequest(path="bad path!", target="example.org")


class TestUpdateShorturl:
    def test_updates_path_and_target(self, db_session: Session):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        new_path = _unique("renamed")
        updated = shorturl_service.update_shorturl(
            db_session, shorturl.id, _request(new_path, target="example.org/new")
        )
        assert updated.path == new_path
        assert updated.target == "http://example.org/new"

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(shorturl_service.ShorturlNotFoundError):
            shorturl_service.update_shorturl(db_session, -1, _request())

    def test_keeping_own_path_does_not_trigger_uniqueness_error(
        self, db_session: Session
    ):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        updated = shorturl_service.update_shorturl(
            db_session, shorturl.id, _request(shorturl.path, target="example.org/x")
        )
        assert updated.target == "http://example.org/x"

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
            shorturl_service.delete_shorturl(db_session, -1)


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
        assert target == "http://example.org/known"
        reloaded = _reload(db_session, shorturl.path)
        assert reloaded.counter == 1
        assert reloaded.latestcall_at is not None

    def test_counter_increments_across_repeated_hits(self, db_session: Session):
        shorturl = shorturl_service.create_shorturl(db_session, _request())
        shorturl_service.resolve_and_record_hit(db_session, shorturl.path)
        shorturl_service.resolve_and_record_hit(db_session, shorturl.path)
        assert _reload(db_session, shorturl.path).counter == 2

    def test_unknown_path_returns_none(self, db_session: Session):
        assert shorturl_service.resolve_and_record_hit(db_session, _unique()) is None

    def test_listall_is_not_special_cased(self, db_session: Session):
        # Regression test for the closed security bug: with no shorturl
        # actually named "listAll", the lookup must fall through to a
        # plain miss, not any kind of dump.
        assert shorturl_service.resolve_and_record_hit(db_session, "listAll") is None
