from pydantic import BaseModel, Field

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import StrictInputModel


class ShorturlRequest(StrictInputModel):
    # 1:1 Legacy's SaveRequest: `regex:/^[a-z0-9\-\/\_]+$/i` -- the
    # character class already covers both cases, no separate "i" flag
    # needed in a Python regex.
    path: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-/]+$")
    target: str = Field(min_length=1, max_length=2048)


class ShorturlResponse(BaseModel):
    id: int
    path: str
    target: str
    counter: int
    latestcall_at: UtcDatetime | None


class ShorturlListResponse(BaseModel):
    # Mirrors Legacy's ShorturlController::index() Inertia props
    # (`urlprefix` + `items`) -- built from Settings.shorturl_domain so
    # dev/prod differ by config only (see app.core.config.Settings).
    urlprefix: str
    items: list[ShorturlResponse]
