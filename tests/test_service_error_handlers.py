"""Exercises app.api.exception_handlers' global handlers on a throwaway
app -- same pattern as tests/test_exception_handlers.py, see that file's
module docstring for why a dedicated app is needed here."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.exception_handlers import register_exception_handlers
from app.services.errors import (
    DomainValidationError,
    FieldError,
    ForbiddenError,
    GeneralValidationError,
    NotFoundError,
    PlainError,
)


class _WidgetNotFoundError(NotFoundError):
    pass


class _WidgetValidationError(DomainValidationError):
    pass


class _WidgetInUseError(GeneralValidationError):
    def __init__(self) -> None:
        super().__init__("Das Widget ist noch in Verwendung.")


class _WidgetInPastError(ForbiddenError):
    def __init__(self) -> None:
        super().__init__("Das Widget liegt bereits in der Vergangenheit.")


class _WidgetConflictError(PlainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Das Widget kann nicht gelöscht werden.")


def _make_test_app() -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/raise-not-found")
    def _raise_not_found() -> None:
        raise _WidgetNotFoundError

    @test_app.get("/raise-validation-error")
    def _raise_validation_error() -> None:
        raise _WidgetValidationError(
            [FieldError("name", "Der Name ist bereits vergeben.")]
        )

    @test_app.get("/raise-in-use")
    def _raise_in_use() -> None:
        raise _WidgetInUseError

    @test_app.get("/raise-in-past")
    def _raise_in_past() -> None:
        raise _WidgetInPastError

    @test_app.get("/raise-conflict")
    def _raise_conflict() -> None:
        raise _WidgetConflictError

    return test_app


def test_not_found_error_returns_generic_404():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-not-found")

    assert response.status_code == 404
    assert response.json() == {"detail": "Nicht gefunden."}


def test_domain_validation_error_returns_422_with_field_errors():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-validation-error")

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "loc": ["body", "name"],
                "msg": "Der Name ist bereits vergeben.",
                "type": "value_error",
            }
        ]
    }


def test_general_validation_error_uses_the_general_field():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-in-use")

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "loc": ["body", "general"],
                "msg": "Das Widget ist noch in Verwendung.",
                "type": "value_error",
            }
        ]
    }


def test_forbidden_error_returns_403_with_bare_string_detail():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-in-past")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Das Widget liegt bereits in der Vergangenheit."
    }


def test_plain_error_uses_its_own_status_code():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-conflict")

    assert response.status_code == 422
    assert response.json() == {"detail": "Das Widget kann nicht gelöscht werden."}
