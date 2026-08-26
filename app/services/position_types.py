from typing import Literal

from app.db.models.choirjob import Choirjob
from app.db.models.instrument import Instrument
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
