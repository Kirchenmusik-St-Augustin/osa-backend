import uuid
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from app.schemas.artist import ArtistRequest
from app.schemas.booking import CastSaveRequest, SendMessageRequest
from app.schemas.propriumwork import PropriumworkRequest
from app.schemas.user import UserRequest
from tests.schemas.forms import (
    PERSON_FORMS,
    ordinariumwork_request,
    performance_request,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel

_ID = "0198a3c4-0000-7000-8000-000000000001"

# The limits are written out here on purpose: a test that read them from the
# schema module could not notice a changed value.
_CATALOGUE = 200
_RECIPIENTS = 500
_PROPRIUM = 50
_REHEARSALS = 20
_FREE_TEXT_LIMIT = 2000


def _ids(count: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(count)]


def _positions(count: int) -> list[dict[str, object]]:
    return [{"id": _ID, "quantity": 1} for _ in range(count)]


def _cast_items(count: int) -> list[dict[str, object]]:
    return [{"id": _ID, "cast": []} for _ in range(count)]


# name -> (builder taking the list, largest allowed size)
_LISTS: dict[str, tuple[Callable[[int], BaseModel], int]] = {
    "message recipients": (
        lambda n: SendMessageRequest.model_validate(
            {"recipient_ids": _ids(n), "message": "Hallo"}
        ),
        _RECIPIENTS,
    ),
    "cast not booked": (
        lambda n: CastSaveRequest.model_validate({"not_booked": [{"id": _ID}] * n}),
        _RECIPIENTS,
    ),
    "cast members of one entry": (
        lambda n: CastSaveRequest.model_validate(
            {
                "cast": {
                    "instruments": [{"id": _ID, "cast": [{"id": _ID, "fee": 0}] * n}]
                }
            }
        ),
        _CATALOGUE,
    ),
    **{
        f"cast {section}": (
            lambda n, section=section: CastSaveRequest.model_validate(
                {"cast": {section: _cast_items(n)}}
            ),
            _CATALOGUE,
        )
        for section in ("instruments", "voices", "choirjobs")
    },
    **{
        f"performance setup {kind}": (
            lambda n, kind=kind: performance_request(setup={kind: _positions(n)}),
            _CATALOGUE,
        )
        for kind in ("instruments", "voices", "choirjobs")
    },
    "performance proprium": (
        lambda n: performance_request(
            proprium=[{"propriumelement_id": _ID, "propriumwork_id": _ID}] * n
        ),
        _PROPRIUM,
    ),
    "performance rehearsals": (
        lambda n: performance_request(
            rehearsals=[{"schedule": "2030-04-01T10:00:00"}] * n
        ),
        _REHEARSALS,
    ),
    **{
        f"ordinariumwork setup {kind}": (
            lambda n, kind=kind: ordinariumwork_request(
                setup={"instruments": [], "voices": [], kind: _positions(n)}
            ),
            _CATALOGUE,
        )
        for kind in ("instruments", "voices")
    },
    **{
        f"user {kind}": (
            lambda n, kind=kind: PERSON_FORMS["user"](**{kind: _ids(n)}),
            _CATALOGUE,
        )
        for kind in ("instruments", "voices", "choirjobs", "roles")
    },
}


@pytest.mark.parametrize("name", sorted(_LISTS))
def test_a_list_at_its_limit_is_accepted(name):
    build, limit = _LISTS[name]

    build(limit)


@pytest.mark.parametrize("name", sorted(_LISTS))
def test_a_list_above_its_limit_is_rejected(name):
    build, limit = _LISTS[name]

    with pytest.raises(ValidationError) as rejected:
        build(limit + 1)

    assert {error["type"] for error in rejected.value.errors()} == {"too_long"}


def test_a_message_to_the_cast_without_recipients_is_rejected():
    with pytest.raises(ValidationError):
        SendMessageRequest.model_validate({"recipient_ids": [], "message": "Hallo"})


@pytest.mark.parametrize("message", ["", " ", "   ", "\t\n"])
def test_a_message_to_the_cast_of_blanks_is_rejected(message):
    with pytest.raises(ValidationError) as rejected:
        SendMessageRequest.model_validate(
            {"recipient_ids": _ids(1), "message": message}
        )

    assert [error["loc"] for error in rejected.value.errors()] == [("message",)]


def test_a_message_to_the_cast_is_stripped_and_limited_after_stripping():
    request = SendMessageRequest.model_validate(
        {"recipient_ids": _ids(1), "message": f"  {'x' * 2000} \n"}
    )

    assert request.message == "x" * 2000
    with pytest.raises(ValidationError):
        SendMessageRequest.model_validate(
            {"recipient_ids": _ids(1), "message": "x" * 2001}
        )


# name -> builder taking the text of one free-text field
_FREE_TEXT: dict[str, Callable[[str], BaseModel]] = {
    "artist description": lambda text: ArtistRequest.model_validate(
        {"surname": "Bach", "givenname": "Johann", "description": text}
    ),
    "proprium work description": lambda text: PropriumworkRequest.model_validate(
        {"name": "Ave Maria", "artist_id": _ID, "description": text}
    ),
    "ordinarium work description": lambda text: ordinariumwork_request(
        description=text
    ),
    "performance description": lambda text: performance_request(description=text),
    "performance extra cost description": lambda text: performance_request(
        extracost_description=text
    ),
}


@pytest.mark.parametrize("name", sorted(_FREE_TEXT))
def test_free_text_at_the_default_limit_is_accepted(name):
    _FREE_TEXT[name]("x" * _FREE_TEXT_LIMIT)


@pytest.mark.parametrize("name", sorted(_FREE_TEXT))
def test_free_text_above_the_default_limit_is_rejected(name):
    with pytest.raises(ValidationError):
        _FREE_TEXT[name]("x" * (_FREE_TEXT_LIMIT + 1))


def test_a_field_with_a_smaller_limit_of_its_own_keeps_it():
    with pytest.raises(ValidationError):
        performance_request(
            rehearsals=[{"schedule": "2030-04-01T10:00:00", "comment": "x" * 31}]
        )
    performance_request(
        rehearsals=[{"schedule": "2030-04-01T10:00:00", "comment": "x" * 30}]
    )


def test_the_user_phone_keeps_its_own_format_rule():
    with pytest.raises(ValidationError):
        UserRequest.model_validate(
            {
                "surname": "Muster",
                "givenname": "Maria",
                "phone": "1" * (_FREE_TEXT_LIMIT + 1),
            }
        )
