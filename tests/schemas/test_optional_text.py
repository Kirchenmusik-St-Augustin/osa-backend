from typing import Annotated, Literal

import pytest
from pydantic import ValidationError

from app.schemas.base import BlankToNone, OptionalText, StrictInputModel


class _Model(StrictInputModel):
    note: OptionalText = None
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


class TestBlankToNoneOnLiterals:
    def test_blank_becomes_none(self):
        assert _Model(kind="").kind is None

    def test_allowed_value_is_kept(self):
        assert _Model(kind="a").kind == "a"

    def test_unknown_value_is_rejected(self):
        with pytest.raises(ValidationError):
            _Model(kind="c")  # type: ignore[arg-type]
