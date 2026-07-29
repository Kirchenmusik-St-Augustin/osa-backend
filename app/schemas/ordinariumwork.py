from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class OrdinariumworkPositionInput(StrictInputModel):
    id: int
    quantity: int = Field(ge=1, le=99)


class OrdinariumworkSetupInput(StrictInputModel):
    instruments: list[OrdinariumworkPositionInput] = Field(default_factory=list)
    voices: list[OrdinariumworkPositionInput] = Field(default_factory=list)


class OrdinariumworkRequest(StrictInputModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    artist_id: int
    duration: int | None = None
    demanding: bool = False
    setup: OrdinariumworkSetupInput


class OrdinariumworkResponse(BaseModel):
    id: int
    name: str
    description: str | None
    artist_id: int
    artist_name: str
    duration: int | None
    demanding: bool


class OrdinariumworkPositionOutput(BaseModel):
    id: int
    name: str
    quantity: int


class OrdinariumworkSetupOutput(BaseModel):
    instruments: list[OrdinariumworkPositionOutput]
    voices: list[OrdinariumworkPositionOutput]


class OrdinariumworkSearchResult(BaseModel):
    id: int
    label: str
