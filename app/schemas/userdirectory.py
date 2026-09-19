import uuid

from pydantic import BaseModel

from app.schemas.performance import PositionRefOutput


class UserDirectoryAbilitiesOutput(BaseModel):
    """Catalog for the Instrument/Voice/Choirjob filter dropdown -- unlike
    UserFormOptionsOutput, roles are deliberately NOT included (only
    instruments/voices/choirjobs are filterable)."""

    instruments: list[PositionRefOutput]
    voices: list[PositionRefOutput]
    choirjobs: list[PositionRefOutput]


class UserDirectoryEntryOutput(BaseModel):
    """One directory entry: `email` is only exposed once the address is
    verified."""

    id: uuid.UUID
    surname: str
    givenname: str
    has_email: bool
    email: str | None
    phone: str | None
