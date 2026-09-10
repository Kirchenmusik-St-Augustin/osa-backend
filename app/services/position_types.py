from typing import Literal

from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
from app.db.models.position_columns_mixin import PositionColumns
from app.db.models.voice import Voice

# Legacy's Relation::morphMap polymorphic target for `position_type` --
# shared by Performance/PerformancePosition (Schritt 5), User/UserPosition
# and Booking/BookingLog (Schritt 6). Extracted here so all three domains
# key off the exact same three literal strings and model classes instead of
# each redefining their own copy (DRY, Schritt 6 plan A.1).
PositionType = Literal["instruments", "voices", "choirjobs"]

POSITION_TYPES: tuple[PositionType, ...] = ("instruments", "voices", "choirjobs")

POSITION_MODELS: dict[PositionType, type[Instrument | Voice | Choirjob]] = {
    "instruments": Instrument,
    "voices": Voice,
    "choirjobs": Choirjob,
}

# Column name on any PositionColumns-mixed-in table for a given
# position_type -- the write/key-extraction counterpart to POSITION_MODELS
# (which maps to the *referenced* lookup table, not the *referencing*
# column). Kept private: position_kwargs()/position_key() below are the
# public surface, so every call site stays agnostic of the exact column
# names.
_POSITION_COLUMN_NAMES: dict[PositionType, str] = {
    "instruments": "instrument_id",
    "voices": "voice_id",
    "choirjobs": "choirjob_id",
}


def position_kwargs(position_type: PositionType, position_id: int) -> dict[str, int]:
    """Build the single-key {instrument_id|voice_id|choirjob_id: position_id}
    keyword-argument dict for constructing a row on one of the four tables
    mixing in PositionColumns, from a (position_type, position_id) pair --
    e.g. `Booking(**position_kwargs(position_type, position_id), ...)`."""
    return {_POSITION_COLUMN_NAMES[position_type]: position_id}


def position_key(row: PositionColumns) -> tuple[PositionType, int]:
    """Reconstruct the (position_type, position_id) pair from whichever of
    a PositionColumns row's three FK columns is populated -- the inverse of
    position_kwargs(), for call sites that used to read row.position_type/
    row.position_id directly."""
    if row.instrument_id is not None:
        return "instruments", row.instrument_id
    if row.voice_id is not None:
        return "voices", row.voice_id
    if row.choirjob_id is not None:
        return "choirjobs", row.choirjob_id
    msg = "position row has none of instrument_id/voice_id/choirjob_id set"
    raise ValueError(msg)
