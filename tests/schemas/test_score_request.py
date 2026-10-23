import pytest
from pydantic import ValidationError

from app.schemas.score import ScoreRequest
from app.schemas.score_fields import SCORE_FIELDS
from app.services import score_service

_REQUIRED_TEXT = ["kasten", "boxnr", "werk"]
_OPTIONAL_TEXT = [
    name
    for name, spec in SCORE_FIELDS.items()
    if spec.kind in {"text", "textarea"} and not spec.required
]


def _score(**fields: object) -> ScoreRequest:
    return ScoreRequest.model_validate(
        {
            **score_service.get_defaults(),
            "kasten": "A",
            "boxnr": "1",
            "inhalt": "Partitur",
            "werk": "Messe in C",
            **fields,
        }
    )


@pytest.mark.parametrize("field", _REQUIRED_TEXT)
@pytest.mark.parametrize("blanks", [" ", "   ", "\t\n"])
def test_a_required_text_made_of_blanks_is_rejected(field, blanks):
    with pytest.raises(ValidationError) as rejected:
        _score(**{field: blanks})

    assert [error["loc"] for error in rejected.value.errors()] == [(field,)]


@pytest.mark.parametrize("field", _REQUIRED_TEXT)
def test_required_text_is_stored_without_surrounding_whitespace(field):
    assert getattr(_score(**{field: "  X1 \n"}), field) == "X1"


@pytest.mark.parametrize("field", _OPTIONAL_TEXT)
def test_optional_text_is_stored_without_surrounding_whitespace(field):
    assert getattr(_score(**{field: "  Wert \t"}), field) == "Wert"


@pytest.mark.parametrize("field", _OPTIONAL_TEXT)
def test_optional_text_of_blanks_becomes_none(field):
    assert getattr(_score(**{field: "   "}), field) is None


@pytest.mark.parametrize("field", ["kasten", "boxnr", "werk", "surname"])
def test_the_length_limit_applies_to_the_stripped_text(field):
    limit = SCORE_FIELDS[field].length
    assert limit is not None

    assert getattr(_score(**{field: f" {'x' * limit} "}), field) == "x" * limit

    with pytest.raises(ValidationError):
        _score(**{field: "x" * (limit + 1)})
