import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.schemas.profile import ProfileUpdateRequest
from app.services import profile_service

_CURRENT_PASSWORD = "Passwort123"


def _unique(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _request(
    *,
    surname: str | None = None,
    givenname: str = "Given",
    email: str | None = None,
    phone: str = "+43 660 1234567",
    change_password: bool = False,
    password: str | None = None,
    password_confirmation: str | None = None,
    auth_password: str = _CURRENT_PASSWORD,
) -> ProfileUpdateRequest:
    return ProfileUpdateRequest(
        surname=surname or _unique("Muster"),
        givenname=givenname,
        email=email or f"{_unique('user')}@example.com",
        phone=phone,
        change_password=change_password,
        password=password,
        password_confirmation=password_confirmation,
        auth_password=auth_password,
    )


class TestSchemaValidation:
    def test_password_confirmation_mismatch_is_rejected_when_changing_password(self):
        with pytest.raises(ValueError, match="Passwort-Bestätigung"):
            ProfileUpdateRequest(
                surname="Muster",
                givenname="Max",
                email="max@example.com",
                phone="+43 660 1234567",
                change_password=True,
                password="NeuesPassw0rt",
                password_confirmation="Anderes1234",
                auth_password=_CURRENT_PASSWORD,
            )

    def test_missing_password_is_rejected_when_changing_password(self):
        with pytest.raises(ValueError, match="erforderlich"):
            ProfileUpdateRequest(
                surname="Muster",
                givenname="Max",
                email="max@example.com",
                phone="+43 660 1234567",
                change_password=True,
                password=None,
                password_confirmation=None,
                auth_password=_CURRENT_PASSWORD,
            )

    def test_password_fields_are_ignored_when_not_changing_password(self):
        # Legacy's controller-level short-circuit -- an arbitrary/invalid
        # password value is harmless when change_password is False.
        request = ProfileUpdateRequest(
            surname="Muster",
            givenname="Max",
            email="max@example.com",
            phone="+43 660 1234567",
            change_password=False,
            password="x",
            password_confirmation="different",
            auth_password=_CURRENT_PASSWORD,
        )
        assert request.password == "x"

    def test_invalid_phone_is_rejected(self):
        with pytest.raises(ValueError, match="Rufnummern-Format"):
            _request(phone="not-a-phone-number")

    def test_empty_auth_password_is_rejected(self):
        with pytest.raises(ValueError):  # noqa: PT011 -- Pydantic's own Field(min_length=1)
            _request(auth_password="")


class TestUpdateProfile:
    def test_wrong_current_password_is_rejected(self, db_session: Session, make_user):
        user = make_user(password=_CURRENT_PASSWORD)
        with pytest.raises(profile_service.WrongCurrentPasswordError):
            profile_service.update_profile(
                db_session, user, _request(auth_password="totally-wrong")
            )

    def test_normalizes_names_and_updates_phone(self, db_session: Session, make_user):
        user = make_user(password=_CURRENT_PASSWORD)
        surname = _unique("muster")
        updated, _ = profile_service.update_profile(
            db_session,
            user,
            _request(surname=surname, givenname="max", phone="+43 664 7654321"),
        )
        assert updated.surname == surname.upper()
        assert updated.givenname == "Max"
        assert updated.phone == "+43 664 7654321"

    def test_duplicate_name_combo_against_another_user_is_rejected(
        self, db_session: Session, make_user
    ):
        surname, givenname = _unique("Doppel"), "Gustav"
        other = make_user()
        # Stored already-normalized, like every real write path leaves it
        # (create_user/update_profile always run normalize_surname/
        # normalize_givenname) -- update_profile() compares against the
        # normalized form of the *new* data too.
        other.surname = surname.upper()
        other.givenname = givenname
        db_session.commit()

        user = make_user(password=_CURRENT_PASSWORD)
        with pytest.raises(profile_service.ProfileValidationError) as exc_info:
            profile_service.update_profile(
                db_session, user, _request(surname=surname, givenname=givenname)
            )
        msg = "Die Kombination von Vor- und Nachname ist vergeben."
        assert exc_info.value.errors == [("surname", msg), ("givenname", msg)]

    def test_keeping_own_name_does_not_trigger_uniqueness_error(
        self, db_session: Session, make_user
    ):
        user = make_user(password=_CURRENT_PASSWORD)
        updated, _ = profile_service.update_profile(
            db_session,
            user,
            _request(surname=user.surname, givenname=user.givenname),
        )
        assert updated.id == user.id

    def test_duplicate_email_against_another_user_is_rejected(
        self, db_session: Session, make_user
    ):
        email = f"{_unique('dup')}@example.com"
        make_user(email=email)
        user = make_user(password=_CURRENT_PASSWORD)

        with pytest.raises(profile_service.ProfileValidationError) as exc_info:
            profile_service.update_profile(db_session, user, _request(email=email))
        assert exc_info.value.errors == [
            ("email", "Diese E-Mail-Adresse ist bereits vergeben.")
        ]

    def test_keeping_own_email_does_not_trigger_uniqueness_error(
        self, db_session: Session, make_user
    ):
        email = f"{_unique('same')}@example.com"
        user = make_user(email=email, password=_CURRENT_PASSWORD)
        updated, email_changed = profile_service.update_profile(
            db_session, user, _request(email=email)
        )
        assert updated.id == user.id
        assert email_changed is False

    def test_email_change_resets_verification_and_reports_changed(
        self, db_session: Session, make_user
    ):
        user = make_user(
            email=f"{_unique('old')}@example.com", password=_CURRENT_PASSWORD
        )
        user.email_verified_at = datetime.now(UTC)
        db_session.commit()

        new_email = f"{_unique('new')}@example.com"
        updated, email_changed = profile_service.update_profile(
            db_session, user, _request(email=new_email)
        )
        assert email_changed is True
        assert updated.email == new_email
        assert updated.email_verified_at is None

    def test_email_case_change_counts_as_changed_raw_comparison(
        self, db_session: Session, make_user
    ):
        # Legacy compares raw strings (`!==`), not case-normalized -- see
        # project_osa_migration_plan memory. Local-part casing specifically
        # (not the domain): Pydantic's EmailStr already lowercases the
        # domain itself, so only a local-part-only case change actually
        # reaches update_profile() with a different string.
        base = _unique("case")
        user = make_user(email=f"{base}@example.com", password=_CURRENT_PASSWORD)
        user.email_verified_at = datetime.now(UTC)
        db_session.commit()

        _, email_changed = profile_service.update_profile(
            db_session, user, _request(email=f"{base.upper()}@example.com")
        )
        assert email_changed is True

    def test_new_password_equal_to_current_is_rejected(
        self, db_session: Session, make_user
    ):
        user = make_user(password=_CURRENT_PASSWORD)
        with pytest.raises(profile_service.ProfileValidationError) as exc_info:
            profile_service.update_profile(
                db_session,
                user,
                _request(
                    change_password=True,
                    password=_CURRENT_PASSWORD,
                    password_confirmation=_CURRENT_PASSWORD,
                ),
            )
        assert exc_info.value.errors[0][0] == "password"

    def test_new_password_actually_changes_the_hash(
        self, db_session: Session, make_user
    ):
        user = make_user(password=_CURRENT_PASSWORD)
        updated, _ = profile_service.update_profile(
            db_session,
            user,
            _request(
                change_password=True,
                password="EinNeuesPassw0rt",
                password_confirmation="EinNeuesPassw0rt",
            ),
        )
        assert verify_password("EinNeuesPassw0rt", updated.auth_password) is True
        assert verify_password(_CURRENT_PASSWORD, updated.auth_password) is False
