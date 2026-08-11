from pydantic import BaseModel

from app.schemas.performance import PositionRefOutput


class UserDirectoryAbilitiesOutput(BaseModel):
    """Catalog for the Instrument/Voice/Choirjob filter dropdown -- unlike
    UserFormOptionsOutput, roles are deliberately NOT included (verified
    against Legacy's UserdirectoryController::index(), whose `abilities`
    prop only ever ships instruments/voices/choirjobs)."""

    instruments: list[PositionRefOutput]
    voices: list[PositionRefOutput]
    choirjobs: list[PositionRefOutput]


class UserDirectoryEntryOutput(BaseModel):
    """Mirrors Legacy's User\\Directory resource: `email` is only exposed
    once the address is verified, mirroring `hasVerifiedEmail()`."""

    id: int
    surname: str
    givenname: str
    has_email: bool
    email: str | None
    phone: str | None
