from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class PropriumworkRequest(StrictInputModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    artist_id: int
    duration: int | None = None
    demanding: bool = False


class PropriumworkResponse(BaseModel):
    id: int
    name: str
    description: str | None
    artist_id: int
    artist_name: str
    duration: int | None
    demanding: bool


class PropriumworkSearchResult(BaseModel):
    id: int
    label: str
