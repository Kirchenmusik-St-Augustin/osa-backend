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
        "+43 664\n1234567",
        "+43 664 1234567\r\n",
        "123",
        "+43 664 abc",
        "+" + "1" * 61,
    ],
)
def test_a_phone_number_outside_the_allowed_format_is_rejected(build, phone):
    with pytest.raises(ValidationError) as rejected:
        build(phone=phone)

    assert [error["loc"] for error in rejected.value.errors()] == [("phone",)]
