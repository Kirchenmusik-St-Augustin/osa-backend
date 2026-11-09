import re
import uuid

from pydantic import BaseModel, Field, field_validator

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import StrictInputModel

# One or more segments of letters (both cases), digits, underscore or hyphen,
# separated by single slashes: no leading, trailing or doubled slash, so what
# is validated is exactly what is stored and looked up.
_PATH_PATTERN = re.compile(r"[a-zA-Z0-9_-]+(/[a-zA-Z0-9_-]+)*")
_PATH_FORMAT_MESSAGE = (
    "Erlaubt sind Buchstaben, Ziffern, _ und -, getrennt durch einzelne "
    "Schrägstriche (kein Schrägstrich am Anfang oder Ende)."
)


class ShorturlRequest(StrictInputModel):
    path: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=2048)

    @field_validator("path")
    @classmethod
    def _path_has_valid_segments(cls, value: str) -> str:
        if not _PATH_PATTERN.fullmatch(value):
            raise ValueError(_PATH_FORMAT_MESSAGE)
        return value


class ShorturlResponse(BaseModel):
    id: uuid.UUID
    path: str
    target: str
    counter: int
    latestcall_at: UtcDatetime | None


class ShorturlListResponse(BaseModel):
    # `urlprefix` is built from Settings.shorturl_domain so dev/prod differ
    # by config only (see app.core.config.Settings).
    urlprefix: str
    items: list[ShorturlResponse]
