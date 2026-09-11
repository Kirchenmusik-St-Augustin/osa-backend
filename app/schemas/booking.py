import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import LenientUuid, StrictInputModel
from app.schemas.fee import FeeResponse
from app.schemas.performance import (
    BookingStatusOutput,
    PerformanceLocationOutput,
    PerformancePropriumOutput,
    PerformanceRehearsalOutput,
    PerformanceSetupOutput,
)

# Field names are snake_case throughout (not Legacy's camelCase `notBooked`)
# -- both this API and osa-frontend are built from scratch here, so there is
# no wire-compatibility reason to mirror Legacy's JSON casing (Schritt 6
# plan A.3). `for` (Legacy's field name on a booking-status "for" position)
# is a reserved Python keyword, renamed to `position`.


class CastMemberInput(StrictInputModel):
    id: LenientUuid
    fee: int = Field(ge=0)


class CastSetupItemInput(StrictInputModel):
    id: LenientUuid
    cast: list[CastMemberInput] = Field(default_factory=list)


class CastSectionInput(StrictInputModel):
    instruments: list[CastSetupItemInput] = Field(default_factory=list)
    voices: list[CastSetupItemInput] = Field(default_factory=list)
    choirjobs: list[CastSetupItemInput] = Field(default_factory=list)


class NotBookedEntryInput(StrictInputModel):
    id: LenientUuid


class CastSaveRequest(StrictInputModel):
    cast: CastSectionInput = Field(default_factory=CastSectionInput)
    not_booked: list[NotBookedEntryInput] = Field(default_factory=list)


class CastMemberOutput(BaseModel):
    id: uuid.UUID
    name: str
    fee: int
    # Only ever populated for choirjobs cast members (auto-sort-by-voice
    # feature) -- instruments/voices members keep both None.
    voice_name: str | None = None
    voice_order: int | None = None


class CastSetupItemOutput(BaseModel):
    id: uuid.UUID
    name: str
    cast: list[CastMemberOutput]


class CastSectionOutput(BaseModel):
    instruments: list[CastSetupItemOutput]
    voices: list[CastSetupItemOutput]
    choirjobs: list[CastSetupItemOutput]


class NotBookedOutput(BaseModel):
    id: uuid.UUID
    name: str


class CastFormData(BaseModel):
    cast: CastSectionOutput
    not_booked: list[NotBookedOutput]


class BookableUserOutput(BaseModel):
    id: uuid.UUID
    name: str
    # Only ever populated for choirjobs candidates -- see CastMemberOutput.
    voice_name: str | None = None
    voice_order: int | None = None


class BookableGroupOutput(BaseModel):
    requesting: list[BookableUserOutput]
    other: list[BookableUserOutput]


class StaffItemOutput(BaseModel):
    id: uuid.UUID
    name: str
    bookable: BookableGroupOutput


class StaffSectionOutput(BaseModel):
    instruments: list[StaffItemOutput]
    voices: list[StaffItemOutput]
    choirjobs: list[StaffItemOutput]


class PopularFrequentUserOutput(BaseModel):
    id: uuid.UUID
    name: str
    total: int


class PopularRecentUserOutput(BaseModel):
    id: uuid.UUID
    name: str
    booked: datetime


class PopularItemOutput(BaseModel):
    frequent: list[PopularFrequentUserOutput]
    recent: list[PopularRecentUserOutput]


class PopularSectionOutput(BaseModel):
    # dict keys are position (Instrument/Voice/Choirjob) ids -- JSON
    # serializes them as strings, the frontend type reflects that.
    instruments: dict[uuid.UUID, PopularItemOutput]
    voices: dict[uuid.UUID, PopularItemOutput]
    choirjobs: dict[uuid.UUID, PopularItemOutput]


class PerformanceShortOutput(BaseModel):
    id: uuid.UUID
    ordinariumwork_name: str
    ordinariumwork_artist_name: str
    artist_name: str | None
    schedule: datetime
    location: PerformanceLocationOutput
    user_booking: BookingStatusOutput
    proprium: list[PerformancePropriumOutput]
    demanding_proprium: bool
    rehearsals: list[PerformanceRehearsalOutput]


class PerformanceCastPageResponse(BaseModel):
    id: uuid.UUID
    ordinariumwork_name: str
    ordinariumwork_artist_name: str
    artist_name: str | None
    schedule: datetime
    rehearsals: list[PerformanceRehearsalOutput]
    location: PerformanceLocationOutput
    demanding_proprium: bool
    setup: PerformanceSetupOutput
    staff: StaffSectionOutput
    form_data: CastFormData
    fees: list[FeeResponse]
    popular: PopularSectionOutput


class BillingPositionOutput(BaseModel):
    id: uuid.UUID | None
    name: str
    fee: int


class BillingItemOutput(BaseModel):
    id: uuid.UUID
    name: str
    quantity: int
    positions: list[BillingPositionOutput]
    sum: int


class BillingTypeOutput(BaseModel):
    items: list[BillingItemOutput]
    sum: int
    count: int


class BillingOrgfeeOutput(BaseModel):
    instruments: int
    choirjobs: int
    sum: int


class BillingExtracostOutput(BaseModel):
    amount: int
    description: str


class BillingOutput(BaseModel):
    instruments: BillingTypeOutput
    voices: BillingTypeOutput
    choirjobs: BillingTypeOutput
    orgfee: BillingOrgfeeOutput
    extracost: BillingExtracostOutput
    sum: int


class PerformanceBillingResponse(PerformanceShortOutput):
    billing: BillingOutput


class RequestOrBookingEntryOutput(BaseModel):
    id: uuid.UUID
    name: str
    status: BookingStatusOutput


class PerformanceRequestsAndBookingsResponse(PerformanceShortOutput):
    entries: list[RequestOrBookingEntryOutput]


class PerformanceMessageToCastResponse(PerformanceShortOutput):
    booked_cast: CastSectionOutput


class MessageRecipientOutput(BaseModel):
    id: uuid.UUID
    surname: str
    givenname: str
    has_email: bool
    email: str | None
    phone: str | None


class SendMessageRequest(StrictInputModel):
    recipient_ids: list[LenientUuid] = Field(min_length=1)
    message: str = Field(min_length=1)
