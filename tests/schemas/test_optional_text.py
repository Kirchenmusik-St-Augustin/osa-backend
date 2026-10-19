from typing import Annotated, Literal

import pytest
from pydantic import Field, ValidationError

from app.schemas.base import BlankToNone, OptionalText, StrictInputModel


class _Model(StrictInputModel):
    note: OptionalText = None
    short: OptionalText = Field(default=None, max_length=5)
    kind: Annotated[Literal["a", "b"] | None, BlankToNone] = None


class TestOptionalText:
    @pytest.mark.parametrize("blank", ["", " ", "\t\n"])
    def test_blank_string_becomes_none(self, blank: str):
        assert _Model(note=blank).note is None

    def test_real_text_is_kept_untouched(self):
        assert _Model(note="  Hallo  ").note == "  Hallo  "

    def test_none_stays_none(self):
        assert _Model(note=None).note is None

    def test_default_is_none(self):
        assert _Model().note is None

    def test_non_string_is_still_rejected_in_strict_mode(self):
        with pytest.raises(ValidationError):
            _Model(note=5)  # type: ignore[arg-type]

    def test_text_at_the_default_limit_is_accepted(self):
        assert _Model(note="x" * 2000).note == "x" * 2000

    def test_text_above_the_default_limit_is_rejected(self):
        with pytest.raises(ValidationError) as rejected:
            _Model(note="x" * 2001)

        assert [error["loc"] for error in rejected.value.errors()] == [("note",)]


class TestOptionalTextWithItsOwnLimit:
    def test_the_smaller_limit_of_the_field_applies(self):
        assert _Model(short="abcde").short == "abcde"
        with pytest.raises(ValidationError):
            _Model(short="abcdef")

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_none_and_blank_stay_possible(self, empty: str | None):
        assert _Model(short=empty).short is None


class TestBlankToNoneOnLiterals:
    def test_blank_becomes_none(self):
        assert _Model(kind="").kind is None

    def test_allowed_value_is_kept(self):
        assert _Model(kind="a").kind == "a"

    def test_unknown_value_is_rejected(self):
        with pytest.raises(ValidationError):
            _Model(kind="c")  # type: ignore[arg-type]
