import uuid

from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class ArtistRequest(StrictInputModel):
    surname: str = Field(min_length=3, max_length=32)
    givenname: str = Field(min_length=3, max_length=32)
    description: str | None = None
    birthyear: int | None = None
    deathyear: int | None = None
    composer: bool = False
    conductor: bool = False


class ArtistResponse(BaseModel):
    id: uuid.UUID
    surname: str
    givenname: str
    description: str | None
    birthyear: int | None
    deathyear: int | None
    composer: bool
    conductor: bool


class ArtistSearchResult(BaseModel):
    id: uuid.UUID
    label: str
