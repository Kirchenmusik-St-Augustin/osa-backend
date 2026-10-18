"""Exercises the global exception handlers on a throwaway app.

Starlette's ServerErrorMiddleware re-raises the original exception under
TestClient's default raise_server_exceptions=True regardless of a
registered handler being present, so a handler can only be observed via
raise_server_exceptions=False -- and doing that against the full app would
also swallow real bugs in unrelated routes, hence the dedicated throwaway
app.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError

from app.api.exception_handlers import (
    register_exception_handlers,
    translate_validation_error,
)


class _StrictModel(BaseModel):
    name: str


class _ModelWithCustomValidator(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def _check_length(cls, v: str) -> str:
        if len(v) < 8:
            msg = "Das Passwort muss mindestens 8 Zeichen lang sein."
            raise ValueError(msg)
        return v


def _make_test_app() -> FastAPI:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/raise-validation-error")
    def _raise_validation_error() -> None:
        _StrictModel.model_validate({})

    @test_app.get("/raise-unhandled")
    def _raise_unhandled() -> None:
        message = "boom"
        raise RuntimeError(message)

    @test_app.get("/raise-integrity-error")
    def _raise_integrity_error() -> None:
        statement = "INSERT ..."
        raise IntegrityError(statement, {}, Exception("orig"))

    @test_app.post("/strict-body")
    def _strict_body(body: _StrictModel) -> dict[str, str]:
        return {"name": body.name}

    @test_app.post("/custom-validator-body")
    def _custom_validator_body(body: _ModelWithCustomValidator) -> dict[str, str]:
        return {"password": body.password}

    return test_app


def test_validation_error_handler_returns_422_with_detail():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-validation-error")

    assert response.status_code == 422
    assert "detail" in response.json()


def test_unhandled_exception_handler_returns_generic_500():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-unhandled")

    assert response.status_code == 500
    assert response.json() == {"detail": "Ein unerwarteter Fehler ist aufgetreten."}


def test_integrity_error_handler_returns_409_with_detail():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.get("/raise-integrity-error")

    assert response.status_code == 409
    assert "detail" in response.json()


def test_request_validation_error_translates_missing_field_to_german():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.post("/strict-body", json={})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(err["msg"] == "Dieses Feld ist erforderlich." for err in detail)


def test_request_validation_error_preserves_custom_german_message():
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    response = client.post("/custom-validator-body", json={"password": "short"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(
        err["msg"] == "Das Passwort muss mindestens 8 Zeichen lang sein."
        for err in detail
    )


def test_translate_validation_error_strips_value_error_prefix():
    message = translate_validation_error(
        {"type": "value_error", "msg": "Value error, Eigene deutsche Meldung."}
    )

    assert message == "Eigene deutsche Meldung."


def test_translate_validation_error_falls_back_to_raw_msg_for_unknown_type():
    message = translate_validation_error(
        {"type": "some_unmapped_type", "msg": "raw text"}
    )

    assert message == "raw text"


def test_validation_errors_never_echo_the_offending_input():
    # A request body and a model validated inside service code share one
    # handler; neither may hand the submitted value (a password, a database
    # row's data) back to the caller.
    client = TestClient(_make_test_app(), raise_server_exceptions=False)

    body_response = client.post("/custom-validator-body", json={"password": "s3cr3t"})
    service_response = client.get("/raise-validation-error")

    for response in (body_response, service_response):
        assert response.status_code == 422
        assert "s3cr3t" not in response.text
        for error in response.json()["detail"]:
            assert set(error) == {"loc", "msg", "type"}
