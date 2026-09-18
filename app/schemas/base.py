import uuid
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class StrictInputModel(BaseModel):
    """Base for every Auth-domain request body -- the project requires
    extra="forbid", strict=True for all input models."""

    model_config = ConfigDict(extra="forbid", strict=True)


# Pydantic's model-level strict=True rejects a UUID-formatted STRING for a
# plain `uuid.UUID` field -- JSON has no native UUID type, so every real
# HTTP request body carries a string here, and strict mode's Python-dict
# validation path (which is what FastAPI actually uses for JSON request
# bodies) doesn't auto-parse it the way non-strict mode would. A per-field
# `strict=False` override is the narrow, documented escape hatch for
# exactly this case -- it does NOT loosen anything else (extra="forbid"
# and every other field's strictness stay untouched). Same technique as
# app.schemas.performance's `_LenientDatetime`, shared here because every
# id field across the whole schema layer needs it.
LenientUuid = Annotated[uuid.UUID, Field(strict=False)]


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


# An optional value that forms submit as an empty (or whitespace-only) string
# when left blank: normalized to None at the schema boundary, so the service
# and database layers only ever see a real value or None -- never "" as a
# stand-in for "no value". Combine with a type, e.g.
# `Annotated[Literal["a", "b"] | None, BlankToNone]`.
BlankToNone = BeforeValidator(_blank_to_none)

OptionalText = Annotated[str | None, BlankToNone]
