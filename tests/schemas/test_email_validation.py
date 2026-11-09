from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from app.schemas.base import EMAIL_MAX_LENGTH
from tests.schemas.forms import EMAIL_FORMS, PERSON_FORMS

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel


@pytest.fixture(params=sorted(EMAIL_FORMS))
def build(request: pytest.FixtureRequest) -> Callable[..., BaseModel]:
    return EMAIL_FORMS[request.param]


def _address(length: int) -> str:
    """A well-formed address of exactly `length` characters."""
    spare = length - len("a" * 64 + "@" + "b" * 60 + "." + ".at")
    return "a" * 64 + "@" + "b" * 60 + "." + "b" * spare + ".at"


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("Anna.Muster@Example.AT", "anna.muster@example.at"),
        ("  anna.muster@example.at  ", "anna.muster@example.at"),
        ("\tANNA.MUSTER@EXAMPLE.AT\n", "anna.muster@example.at"),
    ],
)
def test_an_address_is_stripped_and_lower_cased(build, given, stored):
    assert build(email=given).email == stored


def test_the_longest_allowed_address_is_accepted(build):
    address = _address(EMAIL_MAX_LENGTH)

    assert len(address) == EMAIL_MAX_LENGTH
    assert build(email=address).email == address


def test_an_address_one_character_too_long_is_refused(build):
    address = _address(EMAIL_MAX_LENGTH + 1)

    with pytest.raises(ValidationError) as exc_info:
        build(email=address)

    (error,) = exc_info.value.errors()
    assert error["loc"] == ("email",)
    assert error["type"] == "too_long"
    assert error["ctx"] == {
        "field_type": "Value",
        "max_length": EMAIL_MAX_LENGTH,
        "actual_length": EMAIL_MAX_LENGTH + 1,
    }


@pytest.mark.parametrize("value", ["not-an-address", "anna@", "@example.at", ""])
def test_a_malformed_address_is_refused(build, value):
    with pytest.raises(ValidationError) as exc_info:
        build(email=value)

    assert [error["loc"] for error in exc_info.value.errors()] == [("email",)]


@pytest.mark.parametrize("value", [123, None, ["anna@example.at"]])
def test_a_value_that_is_not_text_is_refused(value):
    # The administrator form is the one place where an address is optional.
    for name, build in EMAIL_FORMS.items():
        if name == "user" and value is None:
            continue
        with pytest.raises(ValidationError) as exc_info:
            build(email=value)
        assert [error["loc"] for error in exc_info.value.errors()] == [("email",)]


def test_the_administrator_form_accepts_a_missing_address():
    assert PERSON_FORMS["user"](email=None).email is None
