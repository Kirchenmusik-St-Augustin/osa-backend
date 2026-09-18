import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class CoreelementType(StrEnum):
    """URL path segment + coreelement_service registry key for the six
    lookup tables (Instrument/Voice/Choirjob/Location/Role/
    Propriumelement), administered through one generic endpoint instead of
    six near-identical modules."""

    instrument = "instrument"
    voice = "voice"
    choirjob = "choirjob"
    location = "location"
    role = "role"
    propriumelement = "propriumelement"


class CoreelementRequest(StrictInputModel):
    """Superset request body holding every possible field (ignored by the
    types that don't use it). Which fields are required/forbidden
    and name/label uniqueness all vary by CoreelementType and are checked
    in coreelement_service against COREELEMENT_CONFIG, since they depend on
    `element_type` -- a sibling *path* parameter the request body itself
    has no access to, not expressible as a static Field constraint here.

    Length bounds below are a best-effort outer safety net, not the
    precise per-type source of truth (that remains COREELEMENT_CONFIG):
    `name`'s max varies by type (60 for five types, 16 for Role alone) --
    60 is used here as the loosest bound that still rejects clearly
    invalid input, so a 17-60 character Role name still passes this layer
    and is correctly rejected by the service's own type-specific check.
    The four extra fields are each used by exactly one type, so their
    bounds here ARE each type's exact, real constraint."""

    name: str = Field(min_length=3, max_length=60)
    label: str | None = Field(default=None, min_length=3, max_length=32)
    description: str | None = Field(default=None, min_length=3, max_length=250)
    address: str | None = Field(default=None, min_length=3, max_length=60)
    color: str | None = Field(default=None, min_length=3, max_length=6)
    # Only instrument/voice/choirjob accept this, everyone else forbids it,
    # same "extra field, forbidden per type" treatment as
    # label/description/address/color, see
    # coreelement_service.CoreelementTypeConfig.has_active_field.
    active: bool | None = None


class CoreelementResponse(BaseModel):
    id: uuid.UUID
    name: str
    order: int
    label: str | None = None
    description: str | None = None
    address: str | None = None
    color: str | None = None
    active: bool | None = None
