from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel
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
# no wire-compatibility reason to mirror Legacy's JSON casing (see
# project_osa_migration_plan memory, Schritt 6 plan A.3). `for` (Legacy's
# field name on a booking-status "for" position) is a reserved Python
# keyword, renamed to `position`.


class CastMemberInput(StrictInputModel):
    id: int
    fee: int = Field(ge=0)


class CastSetupItemInput(StrictInputModel):
    id: int
    cast: list[CastMemberInput] = Field(default_factory=list)


class CastSectionInput(StrictInputModel):
    instruments: list[CastSetupItemInput] = Field(default_factory=list)
    voices: list[CastSetupItemInput] = Field(default_factory=list)
    choirjobs: list[CastSetupItemInput] = Field(default_factory=list)


class NotBookedEntryInput(StrictInputModel):
    id: int


class CastSaveRequest(StrictInputModel):
    cast: CastSectionInput = Field(default_factory=CastSectionInput)
    not_booked: list[NotBookedEntryInput] = Field(default_factory=list)


class CastMemberOutput(BaseModel):
    id: int
    name: str
    fee: int


class CastSetupItemOutput(BaseModel):
    id: int
    name: str
    cast: list[CastMemberOutput]


class CastSectionOutput(BaseModel):
    instruments: list[CastSetupItemOutput]
    voices: list[CastSetupItemOutput]
    choirjobs: list[CastSetupItemOutput]


class NotBookedOutput(BaseModel):
    id: int
    name: str


class CastFormData(BaseModel):
    cast: CastSectionOutput
    not_booked: list[NotBookedOutput]


class BookableUserOutput(BaseModel):
    id: int
    name: str


class BookableGroupOutput(BaseModel):
    requesting: list[BookableUserOutput]
    other: list[BookableUserOutput]


class StaffItemOutput(BaseModel):
    id: int
    name: str
    bookable: BookableGroupOutput


class StaffSectionOutput(BaseModel):
    instruments: list[StaffItemOutput]
    voices: list[StaffItemOutput]
    choirjobs: list[StaffItemOutput]


class PopularFrequentUserOutput(BaseModel):
    id: int
    name: str
    total: int


class PopularRecentUserOutput(BaseModel):
    id: int
    name: str
    booked: datetime


class PopularItemOutput(BaseModel):
    frequent: list[PopularFrequentUserOutput]
    recent: list[PopularRecentUserOutput]


class PopularSectionOutput(BaseModel):
    # dict keys are position (Instrument/Voice/Choirjob) ids -- JSON
    # serializes them as strings, the frontend type reflects that.
    instruments: dict[int, PopularItemOutput]
    voices: dict[int, PopularItemOutput]
    choirjobs: dict[int, PopularItemOutput]


class PerformanceShortOutput(BaseModel):
    id: int
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
    id: int
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
    id: int | None
    name: str
    fee: int


class BillingItemOutput(BaseModel):
    id: int
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
    id: int
    name: str
    status: BookingStatusOutput


class PerformanceRequestsAndBookingsResponse(PerformanceShortOutput):
    entries: list[RequestOrBookingEntryOutput]


class PerformanceMessageToCastResponse(PerformanceShortOutput):
    booked_cast: CastSectionOutput


class MessageRecipientOutput(BaseModel):
    id: int
    surname: str
    givenname: str
    has_email: bool
    email: str | None
    phone: str | None


class SendMessageRequest(StrictInputModel):
    recipient_ids: list[int] = Field(min_length=1)
    message: str = Field(min_length=1)
