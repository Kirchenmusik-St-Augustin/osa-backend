from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from app.schemas.artist import ArtistRequest
from tests.schemas.forms import PERSON_FORMS

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel


def _artist(**fields: object) -> BaseModel:
    return ArtistRequest.model_validate(
        {"surname": "Bach", "givenname": "Johann", **fields}
    )


_FORMS: dict[str, Callable[..., BaseModel]] = {**PERSON_FORMS, "artist": _artist}


@pytest.fixture(params=sorted(_FORMS))
def build(request: pytest.FixtureRequest) -> Callable[..., BaseModel]:
    return _FORMS[request.param]


@pytest.mark.parametrize("field", ["surname", "givenname"])
def test_surrounding_whitespace_is_removed(build, field):
    form = build(**{field: " \t Bach \n"})

    assert getattr(form, field) == "Bach"


@pytest.mark.parametrize("field", ["surname", "givenname"])
def test_whitespace_inside_the_name_is_kept(build, field):
    form = build(**{field: "Maria  Theresa"})

    assert getattr(form, field) == "Maria  Theresa"


@pytest.mark.parametrize("field", ["surname", "givenname"])
@pytest.mark.parametrize("name", ["Li", "J.", "X"])
def test_a_short_name_is_accepted(build, field, name):
    assert getattr(build(**{field: name}), field) == name


@pytest.mark.parametrize("field", ["surname", "givenname"])
@pytest.mark.parametrize("name", ["", " ", "   ", "\t\n"])
def test_a_blank_name_is_rejected(build, field, name):
    with pytest.raises(ValidationError) as rejected:
        build(**{field: name})

    assert [error["loc"] for error in rejected.value.errors()] == [(field,)]


@pytest.mark.parametrize("field", ["surname", "givenname"])
def test_the_length_limit_applies_to_the_stripped_name(build, field):
    assert getattr(build(**{field: f"  {'x' * 32}  "}), field) == "x" * 32

    with pytest.raises(ValidationError):
        build(**{field: "x" * 33})
