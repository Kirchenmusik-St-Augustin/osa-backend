import uuid

from pydantic import BaseModel

from app.schemas.base import OptionalText, PersonName, StrictInputModel


class ArtistRequest(StrictInputModel):
    surname: PersonName
    givenname: PersonName
    description: OptionalText = None
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
