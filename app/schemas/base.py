import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


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
