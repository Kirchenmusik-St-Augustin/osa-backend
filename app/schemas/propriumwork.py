import uuid

from pydantic import BaseModel, Field

from app.schemas.base import LenientUuid, StrictInputModel


class PropriumworkRequest(StrictInputModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    artist_id: LenientUuid
    duration: int | None = None
    demanding: bool = False


class PropriumworkResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    artist_id: uuid.UUID
    artist_name: str
    duration: int | None
    demanding: bool


class PropriumworkSearchResult(BaseModel):
    id: uuid.UUID
    label: str
