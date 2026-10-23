import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.db.models.choirjob import Choirjob
from app.schemas.pagination import MAX_PAGE_SIZE, PageParams
from app.services import user_position_service, userdirectory_service
from tests.sql_capture import recorded_statements

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


_ALL_ROWS = PageParams(limit=MAX_PAGE_SIZE, offset=0)


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

        result = userdirectory_service.list_all_users(db_session, _ALL_ROWS).rows
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

        result = userdirectory_service.list_all_users(db_session, _ALL_ROWS).rows
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
            db_session, "choirjobs", choirjob.id, _ALL_ROWS
        ).rows
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
            db_session, "choirjobs", choirjob.id, _ALL_ROWS
        ).rows
        assert result == []

    def test_unknown_position_id_returns_empty(self, db_session: Session):
        assert (
            userdirectory_service.list_users_for_position(
                db_session, "choirjobs", uuid.uuid4(), _ALL_ROWS
            ).rows
            == []
        )


class TestToEntry:
    def test_verified_address_is_disclosed(self, make_user):
        user = make_user(email="verified@example.test", verified=True)

        entry = userdirectory_service.to_entry(user)

        assert entry.has_email is True
        assert entry.email == "verified@example.test"

    def test_unverified_address_is_withheld(self, make_user):
        user = make_user(email="unverified@example.test", verified=False)

        entry = userdirectory_service.to_entry(user)

        assert entry.has_email is False
        assert entry.email is None


class TestListEntries:
    def test_without_a_type_lists_every_active_user(
        self, db_session: Session, make_user
    ):
        user = make_user()

        page = userdirectory_service.list_entries(db_session, None, None, _ALL_ROWS)

        assert user.id in [entry.id for entry in page.rows]

    def test_type_all_ignores_the_position_id(self, db_session: Session, make_user):
        user = make_user()

        page = userdirectory_service.list_entries(
            db_session, "all", uuid.uuid4(), _ALL_ROWS
        )

        assert user.id in [entry.id for entry in page.rows]

    def test_position_type_with_an_id_lists_only_its_holders(
        self, db_session: Session, make_user
    ):
        choirjob = _make_choirjob(db_session)
        holder, other = make_user(), make_user()
        user_position_service.create_user_position(
            db_session,
            user_id=holder.id,
            position_type="choirjobs",
            position_id=choirjob.id,
        )

        page = userdirectory_service.list_entries(
            db_session, "choirjobs", choirjob.id, _ALL_ROWS
        )

        assert [entry.id for entry in page.rows] == [holder.id]
        assert page.total == 1
        assert other.id not in [entry.id for entry in page.rows]

    def test_position_type_without_an_id_lists_nobody(
        self, db_session: Session, make_user
    ):
        # A holder of another position kind has no instrument id either, so a
        # lookup by a missing id would wrongly match this user.
        choirjob = _make_choirjob(db_session)
        user_position_service.create_user_position(
            db_session,
            user_id=make_user().id,
            position_type="choirjobs",
            position_id=choirjob.id,
        )

        page = userdirectory_service.list_entries(
            db_session, "instruments", None, _ALL_ROWS
        )

        assert list(page.rows) == []
        assert page.total == 0

    def test_statement_count_does_not_grow_with_the_number_of_users(
        self, db_session: Session, make_user
    ):
        make_user()
        with recorded_statements() as few:
            userdirectory_service.list_entries(db_session, None, None, _ALL_ROWS)

        for _ in range(5):
            make_user()
        with recorded_statements() as many:
            userdirectory_service.list_entries(db_session, None, None, _ALL_ROWS)

        assert len(many) == len(few)
