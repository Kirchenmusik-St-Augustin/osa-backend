import uuid
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from app.schemas.ordinariumwork import OrdinariumworkRequest
from app.schemas.propriumwork import PropriumworkRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic import BaseModel


def _ordinarium(**fields: object) -> BaseModel:
    return OrdinariumworkRequest.model_validate(
        {
            "name": "Messe in C",
            "artist_id": str(uuid.uuid4()),
            "setup": {"instruments": [], "voices": []},
            **fields,
        }
    )


def _proprium(**fields: object) -> BaseModel:
    return PropriumworkRequest.model_validate(
        {"name": "Ave Maria", "artist_id": str(uuid.uuid4()), **fields}
    )


@pytest.fixture(params=[_ordinarium, _proprium], ids=["ordinarium", "proprium"])
def build(request: pytest.FixtureRequest) -> Callable[..., BaseModel]:
    return request.param


def test_surrounding_whitespace_of_a_title_is_removed(build):
    assert build(name=" \t Ave Maria \n").name == "Ave Maria"


def test_whitespace_inside_a_title_is_kept(build):
    assert build(name="Sei stille  (Alt Arie)").name == "Sei stille  (Alt Arie)"


@pytest.mark.parametrize("name", ["", "   ", "\t\n", "  ab  ", "ab"])
def test_a_title_without_three_real_characters_is_rejected(build, name):
    with pytest.raises(ValidationError) as rejected:
        build(name=name)

    assert [error["loc"] for error in rejected.value.errors()] == [("name",)]


def test_a_title_of_exactly_three_characters_is_accepted(build):
    assert build(name=" abc ").name == "abc"


def test_the_length_limit_applies_to_the_stripped_title(build):
    assert build(name=f"  {'x' * 60}  ").name == "x" * 60

    with pytest.raises(ValidationError):
        build(name="x" * 61)
