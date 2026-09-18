"""The Score field registry (app.services.score_fields) is deliberately kept
as code, not as database rows (see ARCHITECTURE_DECISIONS.md). Its allowed
values and field list therefore exist next to the Pydantic request model and
the Postgres schema -- these tests pin all three representations together so
a change to one that forgets the others fails here instead of in production.
"""

from typing import Literal, get_args, get_origin

import pytest
from sqlalchemy import Enum

from app.db.models.score import Score
from app.schemas.score import ScoreRequest
from app.services.score_fields import SCORE_FIELDS

_SELECT_FIELDS = [name for name, spec in SCORE_FIELDS.items() if spec.kind == "select"]


def _literal_values(annotation: object) -> list[str]:
    """The Literal[...] members of `Literal[...]` or `Literal[...] | None`."""
    candidates = [annotation, *get_args(annotation)]
    for candidate in candidates:
        if get_origin(candidate) is Literal:
            return list(get_args(candidate))
    pytest.fail(f"no Literal found in {annotation!r}")


def _non_blank(values: tuple[str, ...] | None) -> list[str]:
    assert values is not None
    return [value for value in values if value != ""]


def test_registry_fields_match_the_request_model_and_the_table_columns():
    columns = {column.name for column in Score.__table__.columns}

    assert set(SCORE_FIELDS) == set(ScoreRequest.model_fields)
    assert set(SCORE_FIELDS) <= columns


@pytest.mark.parametrize("name", _SELECT_FIELDS)
def test_select_values_match_the_pydantic_literal(name: str):
    annotation = ScoreRequest.model_fields[name].annotation

    assert _non_blank(SCORE_FIELDS[name].values) == _literal_values(annotation)


@pytest.mark.parametrize("name", _SELECT_FIELDS)
def test_select_values_match_the_postgres_enum_labels(name: str):
    column_type = Score.__table__.c[name].type

    assert isinstance(column_type, Enum)
    assert _non_blank(SCORE_FIELDS[name].values) == list(column_type.enums)


def test_optional_selects_lead_with_a_blank_entry_and_required_ones_do_not():
    for name in _SELECT_FIELDS:
        values = SCORE_FIELDS[name].values
        assert values is not None
        has_blank_entry = values[0] == ""
        assert has_blank_entry is not SCORE_FIELDS[name].required
