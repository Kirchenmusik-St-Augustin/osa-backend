from app.services.errors import (
    DomainValidationError,
    FieldError,
    ForbiddenError,
    GeneralValidationError,
)


class TestFieldError:
    def test_compares_equal_to_a_bare_tuple(self):
        # The service tests compare errors with plain tuples
        # (`.errors == [("field", "message")]`).
        assert FieldError("name", "Der Name ist bereits vergeben.") == (
            "name",
            "Der Name ist bereits vergeben.",
        )

    def test_exposes_named_attributes(self):
        error = FieldError("email", "Diese E-Mail-Adresse ist bereits vergeben.")
        assert error.field == "email"
        assert error.message == "Diese E-Mail-Adresse ist bereits vergeben."


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


class TestForbiddenError:
    def test_fixes_status_code_to_403(self):
        exc = ForbiddenError("Die Aufführung liegt bereits in der Vergangenheit.")
        assert exc.status_code == 403
        assert exc.detail == "Die Aufführung liegt bereits in der Vergangenheit."
