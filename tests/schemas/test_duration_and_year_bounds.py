import pytest
from pydantic import ValidationError

from app.schemas.propriumwork import PropriumworkRequest
from app.schemas.score import ScoreRequest
from app.services import score_service
from tests.schemas.forms import ordinariumwork_request

_ID = "0198a3c4-0000-7000-8000-000000000001"


def _proprium(**fields: object) -> PropriumworkRequest:
    return PropriumworkRequest.model_validate(
        {"name": "Ave Maria", "artist_id": _ID, **fields}
    )


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


@pytest.mark.parametrize("build", [ordinariumwork_request, _proprium])
@pytest.mark.parametrize("duration", [1, 60, 999, None])
def test_a_duration_of_one_to_999_minutes_or_none_is_accepted(build, duration):
    assert build(duration=duration).duration == duration


@pytest.mark.parametrize("build", [ordinariumwork_request, _proprium])
@pytest.mark.parametrize("duration", [0, -1, 1000])
def test_a_duration_outside_one_to_999_is_rejected(build, duration):
    with pytest.raises(ValidationError) as rejected:
        build(duration=duration)

    assert [error["loc"] for error in rejected.value.errors()] == [("duration",)]


@pytest.mark.parametrize("field", ["geboren", "gestorben", "jahr"])
@pytest.mark.parametrize("year", [1, 1685, 9999])
def test_a_real_year_is_accepted(field, year):
    assert getattr(_score(**{field: year}), field) == year


@pytest.mark.parametrize("field", ["geboren", "gestorben", "jahr"])
@pytest.mark.parametrize("year", [0, -5, 10000])
def test_year_zero_and_impossible_years_are_rejected(field, year):
    with pytest.raises(ValidationError) as rejected:
        _score(**{field: year})

    assert [error["loc"] for error in rejected.value.errors()] == [(field,)]


@pytest.mark.parametrize("field", ["geboren", "gestorben", "jahr"])
@pytest.mark.parametrize("blank", ["", "  ", None])
def test_no_year_stays_possible_as_none(field, blank):
    assert getattr(_score(**{field: blank}), field) is None
