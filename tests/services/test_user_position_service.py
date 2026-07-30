import itertools

import pytest
from sqlalchemy.orm import Session

from app.services import user_position_service

# tests/conftest.py's shared SQLite file has no per-test rollback -- small
# fixed position_ids like 1/2/3 collide with residue left by other tests in
# this same file (or a prior run), since position_id has no FK to a real
# instruments/voices/choirjobs row in Phase 1. A monotonically increasing,
# module-life-of-process-unique counter keeps every test's rows disjoint
# (1:1 the `_unique()` name pattern used elsewhere, just for ints).
_id_counter = itertools.count(900_000)


def _unique_id() -> int:
    return next(_id_counter)


class TestGetPositionIdsForUser:
    def test_returns_empty_sets_for_user_without_qualifications(
        self, db_session: Session, make_user
    ):
        user = make_user()
        result = user_position_service.get_position_ids_for_user(db_session, user.id)
        assert result == {"instruments": set(), "voices": set(), "choirjobs": set()}

    def test_groups_qualifications_by_type(self, db_session: Session, make_user):
        user = make_user()
        instrument_a, instrument_b, voice = (
            _unique_id(),
            _unique_id(),
            _unique_id(),
        )
        user_position_service.create_user_position(
            db_session,
            user_id=user.id,
            position_type="instruments",
            position_id=instrument_a,
        )
        user_position_service.create_user_position(
            db_session,
            user_id=user.id,
            position_type="instruments",
            position_id=instrument_b,
        )
        user_position_service.create_user_position(
            db_session, user_id=user.id, position_type="voices", position_id=voice
        )
        result = user_position_service.get_position_ids_for_user(db_session, user.id)
        assert result["instruments"] == {instrument_a, instrument_b}
        assert result["voices"] == {voice}
        assert result["choirjobs"] == set()


class TestGetQualifiedUserIdsBatch:
    def test_groups_users_by_type_and_position(self, db_session: Session, make_user):
        first = make_user()
        second = make_user()
        instrument_id, voice_id = _unique_id(), _unique_id()
        user_position_service.create_user_position(
            db_session,
            user_id=first.id,
            position_type="instruments",
            position_id=instrument_id,
        )
        user_position_service.create_user_position(
            db_session,
            user_id=second.id,
            position_type="instruments",
            position_id=instrument_id,
        )
        user_position_service.create_user_position(
            db_session, user_id=first.id, position_type="voices", position_id=voice_id
        )

        result = user_position_service.get_qualified_user_ids_batch(
            db_session,
            {
                "instruments": {instrument_id},
                "voices": {voice_id},
                "choirjobs": set(),
            },
        )

        assert result[("instruments", instrument_id)] == {first.id, second.id}
        assert result[("voices", voice_id)] == {first.id}

    def test_empty_keys_return_empty_dict(self, db_session: Session):
        result = user_position_service.get_qualified_user_ids_batch(
            db_session, {"instruments": set(), "voices": set(), "choirjobs": set()}
        )
        assert result == {}

    def test_runs_at_most_one_query_per_nonempty_type(
        self, db_session: Session, make_user, count_queries
    ):
        user = make_user()
        ids = {_unique_id(), _unique_id(), _unique_id()}
        for position_id in ids:
            user_position_service.create_user_position(
                db_session,
                user_id=user.id,
                position_type="instruments",
                position_id=position_id,
            )

        with count_queries() as counter:
            user_position_service.get_qualified_user_ids_batch(
                db_session,
                {"instruments": ids, "voices": set(), "choirjobs": set()},
            )
        # One query for the single non-empty type ("instruments"), regardless
        # of how many position_ids are inside it -- the N+1-safety guarantee.
        assert counter.count == 1


class TestIsBookable:
    @pytest.mark.parametrize(
        ("user_ids", "performance_ids", "expected"),
        [
            (
                {"instruments": {1}, "voices": set(), "choirjobs": set()},
                {"instruments": {1}, "voices": set(), "choirjobs": set()},
                True,
            ),
            (
                {"instruments": {1}, "voices": set(), "choirjobs": set()},
                {"instruments": {2}, "voices": set(), "choirjobs": set()},
                False,
            ),
            (
                {"instruments": set(), "voices": {9}, "choirjobs": set()},
                {"instruments": set(), "voices": {9}, "choirjobs": set()},
                True,
            ),
            (
                {"instruments": set(), "voices": set(), "choirjobs": {4}},
                {"instruments": set(), "voices": set(), "choirjobs": {4}},
                True,
            ),
            (
                {"instruments": set(), "voices": set(), "choirjobs": set()},
                {"instruments": {1}, "voices": {2}, "choirjobs": {3}},
                False,
            ),
        ],
    )
    def test_matches_intersection_across_all_three_types(
        self, user_ids, performance_ids, expected
    ):
        assert user_position_service.is_bookable(user_ids, performance_ids) is expected
