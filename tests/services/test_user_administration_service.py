import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from app.core.security import verify_password
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.services import user_administration_service

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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
            user_administration_service.get_user(db_session, uuid.uuid4())

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
            user_administration_service.restore_user(db_session, uuid.uuid4())


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
            user_administration_service.set_random_password(
                db_session, uuid.uuid4(), admin.id
            )


def _soft_delete(db_session: Session, user) -> None:
    user.deleted_at = datetime.now(UTC)
    db_session.commit()


class TestIsPurgeable:
    def test_deleted_user_without_history_is_purgeable(
        self, db_session: Session, make_user
    ):
        user = make_user()
        _soft_delete(db_session, user)

        assert user_administration_service.is_purgeable(db_session, user)

    def test_active_user_is_not_purgeable(self, db_session: Session, make_user):
        user = make_user()

        assert not user_administration_service.is_purgeable(db_session, user)

    @pytest.mark.parametrize("kind", ["booking", "request", "log"])
    def test_any_booking_history_blocks(
        self, db_session: Session, make_user, add_user_history, kind
    ):
        user = make_user()
        add_user_history(user, kind)
        _soft_delete(db_session, user)

        assert not user_administration_service.is_purgeable(db_session, user)


class TestPurgeUser:
    def test_removes_the_row_and_cascades_account_owned_data(
        self, db_session: Session, make_user
    ):
        user = make_user(roles=["purge-test-role"])
        user_id = user.id
        _soft_delete(db_session, user)

        user_administration_service.purge_user(db_session, user_id)

        assert db_session.get(User, user_id) is None
        remaining_roles = db_session.execute(
            select(func.count())
            .select_from(UserRole)
            .where(UserRole.user_id == user_id)
        ).scalar_one()
        assert remaining_roles == 0

    def test_active_user_raises_not_deleted(self, db_session: Session, make_user):
        user = make_user()

        with pytest.raises(user_administration_service.UserNotDeletedError):
            user_administration_service.purge_user(db_session, user.id)
        assert db_session.get(User, user.id) is not None

    @pytest.mark.parametrize("kind", ["booking", "request", "log"])
    def test_booking_history_raises_has_history(
        self, db_session: Session, make_user, add_user_history, kind
    ):
        user = make_user()
        add_user_history(user, kind)
        _soft_delete(db_session, user)

        with pytest.raises(user_administration_service.UserHasHistoryError):
            user_administration_service.purge_user(db_session, user.id)
        assert db_session.get(User, user.id) is not None

    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(user_administration_service.UserAdministrationNotFoundError):
            user_administration_service.purge_user(db_session, uuid.uuid4())
