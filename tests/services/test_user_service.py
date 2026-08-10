import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.datetime_utils import local_now
from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.oauth2_binding import Oauth2Binding
from app.db.models.performance import Performance
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.voice import Voice
from app.schemas.user import UserRequest
from app.services import user_position_service, user_service


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _request(
    *,
    surname: str | None = None,
    givenname: str = "Given",
    email: str | None = None,
    phone: str | None = None,
    auth_locked: bool = False,
    instruments: list[int] | None = None,
    voices: list[int] | None = None,
    choirjobs: list[int] | None = None,
    roles: list[int] | None = None,
) -> UserRequest:
    return UserRequest(
        surname=surname or _unique("Muster"),
        givenname=givenname,
        email=email,
        phone=phone,
        auth_locked=auth_locked,
        instruments=instruments or [],
        voices=voices or [],
        choirjobs=choirjobs or [],
        roles=roles or [],
    )


def _make_instrument(db_session: Session) -> Instrument:
    now = datetime.now(UTC)
    instrument = Instrument(
        name=_unique("Instrument"), order=0, created_at=now, updated_at=now
    )
    db_session.add(instrument)
    db_session.commit()
    return instrument


def _make_voice(db_session: Session) -> Voice:
    now = datetime.now(UTC)
    voice = Voice(name=_unique("Voice"), order=0, created_at=now, updated_at=now)
    db_session.add(voice)
    db_session.commit()
    return voice


def _make_choirjob(db_session: Session) -> Choirjob:
    now = datetime.now(UTC)
    choirjob = Choirjob(
        name=_unique("Choirjob"), order=0, created_at=now, updated_at=now
    )
    db_session.add(choirjob)
    db_session.commit()
    return choirjob


def _make_role(db_session: Session) -> Role:
    role = Role(name=_unique("role"), label=_unique("Label"), order=0)
    db_session.add(role)
    db_session.commit()
    return role


def _make_performance(db_session: Session, *, schedule: datetime) -> Performance:
    # No FK constraints on location_id/ordinariumwork_id in Phase 1 (see
    # app.db.models.performance.Performance docstring) -- arbitrary ints are
    # fine, this test only needs a real `id` + `schedule` to join Bookings
    # against.
    now = datetime.now(UTC)
    performance = Performance(
        schedule=schedule,
        location_id=1,
        ordinariumwork_id=1,
        created_at=now,
        updated_at=now,
    )
    db_session.add(performance)
    db_session.commit()
    return performance


def _make_booking(db_session: Session, *, performance_id: int, user_id: int) -> Booking:
    now = datetime.now(UTC)
    booking = Booking(
        performance_id=performance_id,
        user_id=user_id,
        position_type="instruments",
        position_id=1,
        fee=80,
        order=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(booking)
    db_session.commit()
    return booking


def _make_booking_request(
    db_session: Session, *, performance_id: int, user_id: int
) -> BookingRequest:
    now = datetime.now(UTC)
    booking_request = BookingRequest(
        performance_id=performance_id,
        user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    db_session.add(booking_request)
    db_session.commit()
    return booking_request


class TestSearchUsers:
    def test_matches_combined_surname_comma_givenname(
        self, db_session: Session, make_user
    ):
        marker = _unique("Zwetschke")
        user = make_user()
        user.surname = marker
        user.givenname = "Anton"
        db_session.commit()

        results = user_service.search_users(db_session, f"{marker} anton")
        assert [u.id for u in results] == [user.id]

    def test_empty_query_returns_no_results(self, db_session: Session):
        assert user_service.search_users(db_session, "   ") == []

    def test_excludes_soft_deleted_users(self, db_session: Session, make_user):
        marker = _unique("Geloescht")
        user = make_user()
        user.surname = marker
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        assert user_service.search_users(db_session, marker) == []


class TestGetUser:
    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(user_service.UserNotFoundError):
            user_service.get_user(db_session, -1)

    def test_soft_deleted_user_raises_not_found(self, db_session: Session, make_user):
        user = make_user()
        user.deleted_at = datetime.now(UTC)
        db_session.commit()

        with pytest.raises(user_service.UserNotFoundError):
            user_service.get_user(db_session, user.id)

    def test_returns_positions_ordered_by_canonical_order_not_insertion_order(
        self, db_session: Session, make_user
    ):
        # order=1 inserted first, order=0 (lower) second -- response must
        # still come back order=0 first (see QuantityEditor.vue lesson in
        # project_osa_migration_plan memory).
        first = _make_instrument(db_session)
        first.order = 1
        second = _make_instrument(db_session)
        second.order = 0
        db_session.commit()
        user = make_user()
        user_position_service.create_user_position(
            db_session,
            user_id=user.id,
            position_type="instruments",
            position_id=first.id,
        )
        user_position_service.create_user_position(
            db_session,
            user_id=user.id,
            position_type="instruments",
            position_id=second.id,
        )

        response = user_service.get_user(db_session, user.id)
        assert [i.id for i in response.instruments] == [second.id, first.id]

    def test_includes_oauth2_bindings(self, db_session: Session, make_user):
        user = make_user()
        now = datetime.now(UTC)
        db_session.add(
            Oauth2Binding(
                provider="google",
                remote_id=_unique("remote"),
                remote_name="Test Account",
                local_id=user.id,
                bound_at=now,
                lastuse_at=now,
            )
        )
        db_session.commit()

        response = user_service.get_user(db_session, user.id)
        assert len(response.oauth2_bindings) == 1
        assert response.oauth2_bindings[0].provider == "google"


class TestDeletable:
    def test_no_dependencies_is_deletable(self, db_session: Session, make_user):
        user = make_user()
        assert user_service.get_user(db_session, user.id).deletable is True

    def test_instrument_assignment_alone_does_not_block_delete(
        self, db_session: Session, make_user
    ):
        # Legacy's HasDependencies trait on User only lists `roles` --
        # Instrument/Voice/Choirjob qualifications never block delete.
        instrument = _make_instrument(db_session)
        user = make_user()
        user_position_service.create_user_position(
            db_session,
            user_id=user.id,
            position_type="instruments",
            position_id=instrument.id,
        )
        assert user_service.get_user(db_session, user.id).deletable is True

    def test_assigned_role_blocks_delete(self, db_session: Session, make_user):
        user = make_user(roles=["disponent"])
        assert user_service.get_user(db_session, user.id).deletable is False

    def test_future_confirmed_booking_blocks_delete(
        self, db_session: Session, make_user
    ):
        user = make_user()
        performance = _make_performance(
            db_session, schedule=local_now() + timedelta(days=1)
        )
        _make_booking(db_session, performance_id=performance.id, user_id=user.id)
        assert user_service.get_user(db_session, user.id).deletable is False

    def test_future_open_request_without_booking_does_not_block_delete(
        self, db_session: Session, make_user
    ):
        user = make_user()
        performance = _make_performance(
            db_session, schedule=local_now() + timedelta(days=1)
        )
        _make_booking_request(
            db_session, performance_id=performance.id, user_id=user.id
        )
        assert user_service.get_user(db_session, user.id).deletable is True

    def test_past_confirmed_booking_does_not_block_delete(
        self, db_session: Session, make_user
    ):
        user = make_user()
        performance = _make_performance(
            db_session, schedule=local_now() - timedelta(days=1)
        )
        _make_booking(db_session, performance_id=performance.id, user_id=user.id)
        assert user_service.get_user(db_session, user.id).deletable is True


class TestGetFormOptions:
    def test_returns_catalog_lists(self, db_session: Session):
        instrument = _make_instrument(db_session)
        options = user_service.get_form_options(db_session)
        assert instrument.id in [i.id for i in options.instruments]
        assert isinstance(options.roles, list)


class TestCreateUser:
    def test_normalizes_names(self, db_session: Session, make_user):
        # Lowercased but otherwise unique -- a literal "muster"/"max" would
        # collide with test_auth_service.py's registered user of the exact
        # same normalized name in this suite's shared, non-rolled-back DB.
        admin = make_user(administrator=True)
        surname = _unique("muster")
        response = user_service.create_user(
            db_session, _request(surname=surname, givenname="max"), admin
        )
        assert response.surname == surname.upper()
        assert response.givenname == "Max"

    def test_email_is_optional(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        response = user_service.create_user(db_session, _request(email=None), admin)
        assert response.email is None

    def test_duplicate_name_combo_rejects_both_fields_with_identical_message(
        self, db_session: Session, make_user
    ):
        admin = make_user(administrator=True)
        surname, givenname = _unique("Doppel"), "Gustav"
        user_service.create_user(
            db_session, _request(surname=surname, givenname=givenname), admin
        )
        with pytest.raises(user_service.UserValidationError) as exc_info:
            user_service.create_user(
                db_session, _request(surname=surname, givenname=givenname), admin
            )
        msg = "Die Kombination von Vor- und Nachname ist vergeben."
        assert exc_info.value.errors == [("surname", msg), ("givenname", msg)]

    def test_duplicate_email_is_rejected(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        email = f"{_unique('dup')}@example.com"
        user_service.create_user(db_session, _request(email=email), admin)
        with pytest.raises(user_service.UserValidationError) as exc_info:
            user_service.create_user(db_session, _request(email=email), admin)
        assert exc_info.value.errors == [
            ("email", "Diese E-Mail-Adresse ist bereits vergeben.")
        ]

    def test_syncs_instrument_voice_choirjob_positions(
        self, db_session: Session, make_user
    ):
        admin = make_user(administrator=True)
        instrument = _make_instrument(db_session)
        voice = _make_voice(db_session)
        choirjob = _make_choirjob(db_session)
        response = user_service.create_user(
            db_session,
            _request(
                instruments=[instrument.id], voices=[voice.id], choirjobs=[choirjob.id]
            ),
            admin,
        )
        assert [i.id for i in response.instruments] == [instrument.id]
        assert [v.id for v in response.voices] == [voice.id]
        assert [c.id for c in response.choirjobs] == [choirjob.id]

    def test_disponent_cannot_assign_roles(self, db_session: Session, make_user):
        disponent = make_user(roles=["disponent"])
        role = _make_role(db_session)
        response = user_service.create_user(
            db_session, _request(roles=[role.id]), disponent
        )
        assert response.roles == []

    def test_administrator_can_assign_roles(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        role = _make_role(db_session)
        response = user_service.create_user(
            db_session, _request(roles=[role.id]), admin
        )
        assert [r.id for r in response.roles] == [role.id]


class TestUpdateUser:
    def test_unknown_id_raises_not_found(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        with pytest.raises(user_service.UserNotFoundError):
            user_service.update_user(db_session, -1, _request(), admin)

    def test_administrator_target_is_protected_even_from_another_administrator(
        self, db_session: Session, make_user
    ):
        acting_admin = make_user(administrator=True)
        target_admin = make_user(administrator=True)
        with pytest.raises(user_service.AdministratorProtectedError):
            user_service.update_user(
                db_session, target_admin.id, _request(), acting_admin
            )

    def test_updates_fields(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        user = make_user()
        new_surname = _unique("Neu")
        response = user_service.update_user(
            db_session,
            user.id,
            _request(surname=new_surname, givenname="Anna", phone="+43 660 1234567"),
            admin,
        )
        assert response.surname == new_surname.upper()
        assert response.phone == "+43 660 1234567"

    def test_email_change_resets_verification_without_sending_mail(
        self, db_session: Session, make_user
    ):
        admin = make_user(administrator=True)
        user = make_user(email=f"{_unique('old')}@example.com")
        user.email_verified_at = datetime.now(UTC)
        db_session.commit()

        new_email = f"{_unique('new')}@example.com"
        response = user_service.update_user(
            db_session, user.id, _request(email=new_email), admin
        )
        assert response.email == new_email
        assert response.email_verified_at is None

    def test_keeping_same_email_does_not_reset_verification(
        self, db_session: Session, make_user
    ):
        admin = make_user(administrator=True)
        email = f"{_unique('same')}@example.com"
        user = make_user(email=email)
        user.email_verified_at = datetime.now(UTC)
        db_session.commit()

        response = user_service.update_user(
            db_session, user.id, _request(email=email), admin
        )
        assert response.email_verified_at is not None

    def test_disponent_cannot_assign_roles(self, db_session: Session, make_user):
        disponent = make_user(roles=["disponent"])
        user = make_user()
        role = _make_role(db_session)
        response = user_service.update_user(
            db_session, user.id, _request(roles=[role.id]), disponent
        )
        assert response.roles == []

    def test_position_sync_removes_unselected_positions(
        self, db_session: Session, make_user
    ):
        admin = make_user(administrator=True)
        instrument_a, instrument_b = (
            _make_instrument(db_session),
            _make_instrument(db_session),
        )
        user = make_user()
        user_service.update_user(
            db_session,
            user.id,
            _request(instruments=[instrument_a.id, instrument_b.id]),
            admin,
        )
        response = user_service.update_user(
            db_session, user.id, _request(instruments=[instrument_b.id]), admin
        )
        assert [i.id for i in response.instruments] == [instrument_b.id]


class TestDeleteUser:
    def test_unknown_id_raises_not_found(self, db_session: Session):
        with pytest.raises(user_service.UserNotFoundError):
            user_service.delete_user(db_session, -1)

    def test_administrator_target_is_protected(self, db_session: Session, make_user):
        admin = make_user(administrator=True)
        with pytest.raises(user_service.AdministratorProtectedError):
            user_service.delete_user(db_session, admin.id)

    def test_user_with_assigned_role_cannot_be_deleted(
        self, db_session: Session, make_user
    ):
        user = make_user(roles=["disponent"])
        with pytest.raises(user_service.UserInUseError):
            user_service.delete_user(db_session, user.id)

    def test_deletable_user_is_soft_deleted(self, db_session: Session, make_user):
        user = make_user()
        user_service.delete_user(db_session, user.id)

        deleted = db_session.get(User, user.id)
        assert deleted is not None
        assert deleted.deleted_at is not None
        with pytest.raises(user_service.UserNotFoundError):
            user_service.get_user(db_session, user.id)
