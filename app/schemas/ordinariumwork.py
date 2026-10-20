import uuid

from pydantic import BaseModel, Field

from app.schemas.base import (
    MAX_CATALOGUE_ENTRIES,
    LenientUuid,
    OptionalText,
    StrictInputModel,
    WorkName,
)


class OrdinariumworkPositionInput(StrictInputModel):
    id: LenientUuid
    quantity: int = Field(ge=1, le=99)


class OrdinariumworkSetupInput(StrictInputModel):
    instruments: list[OrdinariumworkPositionInput] = Field(
        default_factory=list, max_length=MAX_CATALOGUE_ENTRIES
    )
    voices: list[OrdinariumworkPositionInput] = Field(
        default_factory=list, max_length=MAX_CATALOGUE_ENTRIES
    )


class OrdinariumworkRequest(StrictInputModel):
    name: WorkName
    description: OptionalText = None
    artist_id: LenientUuid
    duration: int | None = Field(default=None, ge=1, le=999)
    demanding: bool = False
    setup: OrdinariumworkSetupInput


class OrdinariumworkResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    artist_id: uuid.UUID
    artist_name: str
    duration: int | None
    demanding: bool


class OrdinariumworkPositionOutput(BaseModel):
    id: uuid.UUID
    name: str
    quantity: int
    # Lets the frontend flag a setup row whose Instrument/Voice has since
    # been archived -- get_setup() resolves existing rows by id regardless
    # of active status, so a since-archived position still shows up here
    # correctly, just visibly marked.
    active: bool


class OrdinariumworkSetupOutput(BaseModel):
    instruments: list[OrdinariumworkPositionOutput]
    voices: list[OrdinariumworkPositionOutput]


class OrdinariumworkSearchResult(BaseModel):
    id: uuid.UUID
    label: str


class AvailablePositionOutput(BaseModel):
    id: uuid.UUID
    name: str


class OrdinariumworkAvailablePositionsOutput(BaseModel):
    instruments: list[AvailablePositionOutput]
    voices: list[AvailablePositionOutput]
