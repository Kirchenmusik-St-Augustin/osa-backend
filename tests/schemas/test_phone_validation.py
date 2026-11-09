from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from tests.schemas.forms import PERSON_FORMS

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel


@pytest.fixture(params=sorted(PERSON_FORMS))
def build(request: pytest.FixtureRequest) -> Callable[..., BaseModel]:
    return PERSON_FORMS[request.param]


@pytest.mark.parametrize(
    "phone", ["+43 664 1234567", "0664/1234567", "(01) 234-567", "1234"]
)
def test_a_phone_number_in_the_allowed_format_is_accepted(build, phone):
    build(phone=phone)


@pytest.mark.parametrize(
    "phone",
    [
        "+43 664 1234567\n",
        "\n+43 664 1234567",
        "+43 664 1234567\r\n",
        "  +43 664 1234567  ",
        "\t0664/1234567 ",
    ],
)
def test_blanks_around_a_phone_number_are_removed_before_it_is_checked(build, phone):
    assert build(phone=phone).phone == phone.strip()


@pytest.mark.parametrize(
    "phone",
    [
        "+43 664\n1234567",
        "+43 664 1234567\n 1",
        "123",
        "+43 6",
        "((((",
        "/ / / /",
        "+ 12 3",
        "+43 664 abc",
        "abc 1234",
        "+" + "1" * 61,
    ],
)
def test_a_phone_number_outside_the_allowed_format_is_rejected(build, phone):
    with pytest.raises(ValidationError) as rejected:
        build(phone=phone)

    assert [error["loc"] for error in rejected.value.errors()] == [("phone",)]


def test_every_form_refuses_with_the_same_message(build):
    with pytest.raises(ValidationError) as rejected:
        build(phone="((((")

    assert [error["msg"] for error in rejected.value.errors()] == [
        "Value error, Das Rufnummern-Format ist ungültig."
    ]


@pytest.mark.parametrize("phone", ["", "   ", "\n"])
def test_a_blank_phone_number_is_refused_where_it_is_required(phone):
    for name in ("register", "profile"):
        with pytest.raises(ValidationError):
            PERSON_FORMS[name](phone=phone)


@pytest.mark.parametrize("phone", ["", "   ", "\n", None])
def test_a_blank_phone_number_becomes_none_where_it_is_optional(phone):
    assert PERSON_FORMS["user"](phone=phone).phone is None
