import uuid
from typing import Literal

from pydantic import BaseModel

DirectoryType = Literal["all", "instruments", "voices", "choirjobs"]


from app.schemas.base import IdNameOutput


class UserDirectoryAbilitiesOutput(BaseModel):
    """Catalog for the Instrument/Voice/Choirjob filter dropdown -- unlike
    UserFormOptionsOutput, roles are deliberately NOT included (only
    instruments/voices/choirjobs are filterable)."""

    instruments: list[IdNameOutput]
    voices: list[IdNameOutput]
    choirjobs: list[IdNameOutput]


class UserDirectoryEntryOutput(BaseModel):
    """One directory entry: `email` is only exposed once the address is
    verified."""

    id: uuid.UUID
    surname: str
    givenname: str
    has_email: bool
    email: str | None
    phone: str | None
