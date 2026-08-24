from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.core.datetime_utils import UtcDatetime
from app.schemas.base import StrictInputModel

# Pydantic's model-level strict=True (StrictInputModel) rejects ISO-8601
# datetime STRINGS for a plain `datetime` field -- JSON has no native
# datetime type, so every real HTTP request body carries a string here, and
# strict mode's Python-dict validation path (which is what FastAPI actually
# uses for JSON request bodies) doesn't auto-parse it like non-strict mode
# would. A per-field `strict=False` override is the narrow, documented
# escape hatch for exactly this case -- it does NOT loosen anything else
# (extra="forbid" and every other field's strictness are untouched).
_LenientDatetime = Annotated[datetime, Field(strict=False)]


class PerformancePositionInput(StrictInputModel):
    id: int
    quantity: int = Field(ge=1, le=99)


class PerformanceSetupInput(StrictInputModel):
    instruments: list[PerformancePositionInput] = Field(default_factory=list)
    voices: list[PerformancePositionInput] = Field(default_factory=list)
    choirjobs: list[PerformancePositionInput] = Field(default_factory=list)


class PerformanceRehearsalInput(StrictInputModel):
    schedule: _LenientDatetime
    comment: str | None = Field(default=None, max_length=30)


class PerformancePropriumEntryInput(StrictInputModel):
    propriumelement_id: int
    propriumwork_id: int


class PerformanceRequest(StrictInputModel):
    schedule: _LenientDatetime
    location_id: int
    ordinariumwork_id: int
    artist_id: int | None = None
    description: str | None = None
    choirjob_defaultfee: int = Field(ge=0)
    instrument_defaultfee: int = Field(ge=0)
    voice_defaultfee: int = Field(ge=0)
    extracost_amount: int | None = Field(default=None, ge=0)
    extracost_description: str | None = None
    setup: PerformanceSetupInput
    proprium: list[PerformancePropriumEntryInput] = Field(default_factory=list)
    rehearsals: list[PerformanceRehearsalInput] = Field(default_factory=list)


class PerformanceResponse(BaseModel):
    id: int
    schedule: datetime
    location_id: int
    ordinariumwork_id: int
    artist_id: int | None
    description: str | None
    choirjob_defaultfee: int
    instrument_defaultfee: int
    voice_defaultfee: int
    extracost_amount: int | None
    extracost_description: str | None


class PerformancePositionOutput(BaseModel):
    id: int
    name: str
    quantity: int
    # Lets the frontend flag a setup row whose Instrument/Voice/Choirjob
    # has since been archived (osa-only `active` addition, outside the
    # structural 1:1 transfer's scope) -- get_setup() resolves existing rows
    # by id regardless of active status, so a since-archived position
    # still shows up here correctly, just visibly marked.
    active: bool


class PerformanceSetupOutput(BaseModel):
    instruments: list[PerformancePositionOutput]
    voices: list[PerformancePositionOutput]
    choirjobs: list[PerformancePositionOutput]


class PerformancePropriumOutput(BaseModel):
    propriumelement_id: int
    propriumelement_name: str
    propriumwork_id: int
    propriumwork_name: str
    artist_name: str
    description: str | None
    demanding: bool


class PerformanceRehearsalOutput(BaseModel):
    schedule: datetime
    comment: str | None


class PerformanceLocationOutput(BaseModel):
    id: int
    name: str
    color: str
    address: str | None


class PositionRefOutput(BaseModel):
    id: int
    name: str


class BookingStatusOutput(BaseModel):
    """Port of `userBookingStatus()`'s 6-state result: 0=not bookable,
    1=bookable/unrequested, 2=requested, 3=standby, 4=booked/regular,
    5=rejected ("nicht gebucht"). Lives here (not app.schemas.booking)
    because PerformanceCalendarItem below needs it too, and booking.py
    already depends on this module for Location/Proprium/Rehearsal/Setup --
    the other direction would be circular."""

    status: int
    position: PositionRefOutput | None = None
    at: UtcDatetime | None = None


class PerformanceCalendarItem(BaseModel):
    id: int
    schedule: datetime
    location: PerformanceLocationOutput
    ordinariumwork_id: int
    ordinariumwork_name: str
    ordinariumwork_artist_name: str
    ordinariumwork_demanding: bool
    artist_name: str | None
    user_booking: BookingStatusOutput
    proprium: list[PerformancePropriumOutput]
    demanding_proprium: bool
    rehearsals: list[PerformanceRehearsalOutput]


class PerformanceShowResponse(BaseModel):
    id: int
    schedule: datetime
    location: PerformanceLocationOutput
    ordinariumwork_id: int
    ordinariumwork_name: str
    ordinariumwork_artist_name: str
    ordinariumwork_artist_description: str | None
    ordinariumwork_description: str | None
    ordinariumwork_demanding: bool
    artist_id: int | None
    artist_name: str | None
    artist_description: str | None
    description: str | None
    rehearsals: list[PerformanceRehearsalOutput]
    setup: PerformanceSetupOutput
    proprium: list[PerformancePropriumOutput]
    demanding_proprium: bool


class PerformanceFormData(BaseModel):
    id: int
    schedule: datetime
    location_id: int
    ordinariumwork_id: int
    ordinariumwork_label: str
    artist_id: int | None
    description: str | None
    choirjob_defaultfee: int
    instrument_defaultfee: int
    voice_defaultfee: int
    extracost_amount: int | None
    extracost_description: str | None
    setup: PerformanceSetupOutput
    proprium: list[PerformancePropriumOutput]
    rehearsals: list[PerformanceRehearsalOutput]
    deletable: bool


class AvailablePositionOutput(BaseModel):
    id: int
    name: str


class PerformanceAvailableData(BaseModel):
    conductors: list[AvailablePositionOutput]
    instruments: list[AvailablePositionOutput]
    voices: list[AvailablePositionOutput]
    choirjobs: list[AvailablePositionOutput]
    locations: list[PerformanceLocationOutput]
    propriumelements: list[AvailablePositionOutput]
