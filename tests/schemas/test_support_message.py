import uuid

import pytest
from pydantic import ValidationError

from app.schemas.support import MessageToContactpersonRequest


def _request(message: str) -> MessageToContactpersonRequest:
    return MessageToContactpersonRequest.model_validate(
        {"recipient_id": str(uuid.uuid4()), "message": message}
    )


@pytest.mark.parametrize("message", ["   ", "\t\n  ", "  ab  ", "ab", ""])
def test_a_message_without_three_real_characters_is_rejected(message):
    with pytest.raises(ValidationError) as rejected:
        _request(message)

    assert [error["loc"] for error in rejected.value.errors()] == [("message",)]


def test_a_message_is_stored_without_surrounding_whitespace():
    assert _request("  Guten Tag  \n").message == "Guten Tag"


def test_a_message_of_exactly_three_characters_is_accepted():
    assert _request(" abc ").message == "abc"


def test_the_length_limit_applies_to_the_stripped_message():
    assert _request(f"  {'x' * 2000}  ").message == "x" * 2000

    with pytest.raises(ValidationError):
        _request("x" * 2001)
