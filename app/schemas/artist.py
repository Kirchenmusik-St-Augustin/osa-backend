from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class ArtistRequest(StrictInputModel):
    surname: str = Field(min_length=1, max_length=255)
    givenname: str = Field(min_length=1, max_length=255)
    description: str | None = None
    birthyear: int | None = None
    deathyear: int | None = None
    composer: bool = False
    conductor: bool = False


class ArtistResponse(BaseModel):
    id: int
    surname: str
    givenname: str
    description: str | None
    birthyear: int | None
    deathyear: int | None
    composer: bool
    conductor: bool


class ArtistSearchResult(BaseModel):
    id: int
    label: str
