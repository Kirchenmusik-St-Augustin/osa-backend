import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.choirjob import Choirjob
from app.services import user_position_service, userdirectory_service


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _make_choirjob(db_session: Session) -> Choirjob:
    now = datetime.now(UTC)
    choirjob = Choirjob(
        name=_unique("Choirjob"), order=0, created_at=now, updated_at=now
    )
    db_session.add(choirjob)
    db_session.commit()
    return choirjob


class TestGetAbilities:
    def test_does_not_include_roles(self, db_session: Session):
        # Verified against Legacy's UserdirectoryController::index() --
        # `abilities` only ever ships instruments/voices/choirjobs.
        options = userdirectory_service.get_abilities(db_session)
        assert not hasattr(options, "roles")

    def test_lists_real_choirjobs(self, db_session: Session):
        choirjob = _make_choirjob(db_session)
        options = userdirectory_service.get_abilities(db_session)
        assert choirjob.id in [item.id for item in options.choirjobs]


class TestListAllUsers:
    def test_excludes_soft_deleted_users(self, db_session: Session, make_user):
        marker = _unique("Geloescht")
        user = make_user()
        user.surname = marker
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        result = userdirectory_service.list_all_users(db_session)
        assert user.id not in [u.id for u in result]

    def test_includes_active_users_sorted_by_surname(
        self, db_session: Session, make_user
    ):
        marker_a, marker_z = _unique("AAA"), _unique("ZZZ")
        user_z = make_user()
        user_z.surname = marker_z
        user_a = make_user()
        user_a.surname = marker_a
        db_session.commit()

        result = userdirectory_service.list_all_users(db_session)
        ids = [u.id for u in result]
        assert ids.index(user_a.id) < ids.index(user_z.id)


class TestListUsersForPosition:
    def test_matches_users_with_that_position(self, db_session: Session, make_user):
        choirjob = _make_choirjob(db_session)
        user = make_user()
        user_position_service.create_user_position(
            db_session,
            user_id=user.id,
            position_type="choirjobs",
            position_id=choirjob.id,
        )

        result = userdirectory_service.list_users_for_position(
            db_session, "choirjobs", choirjob.id
        )
        assert [u.id for u in result] == [user.id]

    def test_excludes_soft_deleted_users(self, db_session: Session, make_user):
        choirjob = _make_choirjob(db_session)
        user = make_user()
        user_position_service.create_user_position(
            db_session,
            user_id=user.id,
            position_type="choirjobs",
            position_id=choirjob.id,
        )
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        result = userdirectory_service.list_users_for_position(
            db_session, "choirjobs", choirjob.id
        )
        assert result == []

    def test_unknown_position_id_returns_empty(self, db_session: Session):
        assert (
            userdirectory_service.list_users_for_position(db_session, "choirjobs", -1)
            == []
        )
