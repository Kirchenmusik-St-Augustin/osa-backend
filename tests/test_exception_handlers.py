"""Exercises main.py's global exception handlers on a throwaway app.

httpx's ASGITransport re-raises exceptions from the app by default, which
would bypass the handler under test entirely -- raise_app_exceptions=False
lets the handler actually run and produce a response, same reasoning
vb-api's own equivalent test module documents.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ValidationError

from main import _unhandled_exception_handler, _validation_error_handler


class _StrictModel(BaseModel):
    name: str


def _make_test_app() -> FastAPI:
    test_app = FastAPI()
    test_app.add_exception_handler(ValidationError, _validation_error_handler)
    test_app.add_exception_handler(Exception, _unhandled_exception_handler)

    @test_app.get("/raise-validation-error")
    def _raise_validation_error() -> None:
        _StrictModel.model_validate({})

    @test_app.get("/raise-unhandled")
    def _raise_unhandled() -> None:
        message = "boom"
        raise RuntimeError(message)

    return test_app


async def test_validation_error_handler_returns_422_with_detail():
    transport = ASGITransport(app=_make_test_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/raise-validation-error")

    assert response.status_code == 422
    assert "detail" in response.json()


async def test_unhandled_exception_handler_returns_generic_500():
    transport = ASGITransport(app=_make_test_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/raise-unhandled")

    assert response.status_code == 500
    assert response.json() == {"detail": "Ein unerwarteter Fehler ist aufgetreten."}
