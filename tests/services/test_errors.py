from app.services.errors import (
    DomainValidationError,
    FieldError,
    ForbiddenError,
    GeneralValidationError,
    NotFoundError,
    PlainError,
)


class TestNotFoundError:
    def test_a_domain_subclass_is_still_a_not_found_error(self):
        class _ArtistNotFoundError(NotFoundError):
            pass

        assert isinstance(_ArtistNotFoundError(), NotFoundError)


class TestFieldError:
    def test_compares_equal_to_a_bare_tuple(self):
        # Existing service tests written before this hierarchy assert
        # `.errors == [("field", "message")]` -- a NamedTuple must keep
        # comparing equal to a plain tuple for those to keep working.
        assert FieldError("name", "Der Name ist bereits vergeben.") == (
            "name",
            "Der Name ist bereits vergeben.",
        )

    def test_exposes_named_attributes(self):
        error = FieldError("email", "Diese E-Mail-Adresse ist bereits vergeben.")
        assert error.field == "email"
        assert error.message == "Diese E-Mail-Adresse ist bereits vergeben."


class TestDomainValidationError:
    def test_stores_the_given_errors(self):
        errors = [FieldError("name", "msg")]
        exc = DomainValidationError(errors)
        assert exc.errors == errors

    def test_a_domain_subclass_is_still_a_domain_validation_error(self):
        class _ScoreValidationError(DomainValidationError):
            pass

        exc = _ScoreValidationError([FieldError("werk", "Duplikat.")])
        assert isinstance(exc, DomainValidationError)
        assert exc.errors == [("werk", "Duplikat.")]


class TestGeneralValidationError:
    def test_defaults_to_the_general_field(self):
        exc = GeneralValidationError("Das Element ist noch in Verwendung.")
        assert exc.errors == [("general", "Das Element ist noch in Verwendung.")]

    def test_accepts_a_specific_field(self):
        exc = GeneralValidationError(
            "Das bestehende Passwort ist falsch.", field="auth_password"
        )
        assert exc.errors == [("auth_password", "Das bestehende Passwort ist falsch.")]

    def test_is_a_domain_validation_error(self):
        assert isinstance(GeneralValidationError("msg"), DomainValidationError)


class TestPlainError:
    def test_stores_the_detail_message(self):
        class _FixedStatusError(PlainError):
            status_code = 422

        exc = _FixedStatusError("Ein Fehler ist aufgetreten.")
        assert exc.detail == "Ein Fehler ist aufgetreten."
        assert exc.status_code == 422


class TestForbiddenError:
    def test_fixes_status_code_to_403(self):
        exc = ForbiddenError("Die Aufführung liegt bereits in der Vergangenheit.")
        assert exc.status_code == 403
        assert exc.detail == "Die Aufführung liegt bereits in der Vergangenheit."
