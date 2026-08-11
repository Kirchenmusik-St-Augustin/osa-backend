import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.services import user_administration_service


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


class TestSearchUsersIncludingDeleted:
    def test_finds_soft_deleted_users_too(self, db_session: Session, make_user):
        marker = _unique("Geloescht")
        user = make_user()
        user.surname = marker
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        results = user_administration_service.search_users_including_deleted(
            db_session, marker
        )
        assert [u.id for u in results] == [user.id]

    def test_empty_query_returns_no_results(self, db_session: Session):
        assert (
            user_administration_service.search_users_including_deleted(db_session, "  ")
            == []
        )


class TestListDeletedUsers:
    def test_only_returns_soft_deleted_users(self, db_session: Session, make_user):
        active = make_user()
        deleted = make_user()
        deleted.deleted_at = datetime.now(UTC)
        db_session.commit()

        result = user_administration_service.list_deleted_users(db_session)
        ids = [u.id for u in result]
        assert deleted.id in ids
        assert active.id not in ids


class TestGetUser:
    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(user_administration_service.UserAdministrationNotFoundError):
            user_administration_service.get_user(db_session, -1)

    def test_finds_soft_deleted_users_too(self, db_session: Session, make_user):
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        found = user_administration_service.get_user(db_session, user.id)
        assert found.id == user.id


class TestRestoreUser:
    def test_clears_deleted_at(self, db_session: Session, make_user):
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        restored = user_administration_service.restore_user(db_session, user.id)
        assert restored.deleted_at is None

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(user_administration_service.UserAdministrationNotFoundError):
            user_administration_service.restore_user(db_session, -1)


class TestUnlockUser:
    def test_clears_auth_locked(self, db_session: Session, make_user):
        user = make_user(auth_locked=True)
        unlocked = user_administration_service.unlock_user(db_session, user.id)
        assert unlocked.auth_locked is False


class TestSetRandomPassword:
    def test_generates_a_new_working_password(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        target = make_user(password="original-password")

        _, plain_password = user_administration_service.set_random_password(
            db_session, target.id, admin.id
        )

        assert len(plain_password) == 10
        assert verify_password(plain_password, target.auth_password) is True
        assert verify_password("original-password", target.auth_password) is False

    def test_self_targeting_is_rejected(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        with pytest.raises(user_administration_service.SelfTargetError):
            user_administration_service.set_random_password(
                db_session, admin.id, admin.id
            )

    def test_unknown_id_raises_not_found(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        with pytest.raises(user_administration_service.UserAdministrationNotFoundError):
            user_administration_service.set_random_password(db_session, -1, admin.id)
