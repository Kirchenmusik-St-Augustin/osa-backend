from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.base import StrictInputModel


class CoreelementType(StrEnum):
    """URL path segment + coreelement_service registry key for Legacy's six
    `HasCoreelementFeatures` lookup tables (Instrument/Voice/Choirjob/
    Location/Role/Propriumelement), administered through one generic
    endpoint instead of six near-identical modules -- Legacy itself already
    does this via a single `type`-prop-driven Vue page, see
    project_osa_migration_plan memory, Schritt 3."""

    instrument = "instrument"
    voice = "voice"
    choirjob = "choirjob"
    location = "location"
    role = "role"
    propriumelement = "propriumelement"


class CoreelementRequest(StrictInputModel):
    """Superset request body, mirroring Legacy's own generic
    Coreelement/Index.vue form (`defaultValues` holds every possible field,
    "however ignored by other types"). Pydantic only enforces types here --
    the exact per-type length bounds, which fields are required/forbidden,
    and name/label uniqueness all vary by CoreelementType and are checked
    in coreelement_service against COREELEMENT_CONFIG, since they can't be
    expressed as static Field constraints shared across all six types."""

    name: str = Field(min_length=1, max_length=255)
    label: str | None = None
    description: str | None = None
    address: str | None = None
    color: str | None = None


class CoreelementResponse(BaseModel):
    id: int
    name: str
    order: int
    label: str | None = None
    description: str | None = None
    address: str | None = None
    color: str | None = None
