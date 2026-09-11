import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class PositionColumns:
    """Three mutually-exclusive nullable foreign keys replacing the old
    `position_type` (native enum) + `position_id` (plain int, no FK) pair --
    the standard relational "exclusive arc" pattern for representing a
    polymorphic reference with real referential integrity. Exactly one of
    the three is ever non-null, enforced per concrete table by a
    `num_nonnulls(...) = 1` CHECK constraint declared in that table's own
    __table_args__ (not here, to keep this mixin a pure column declaration).

    ON DELETE RESTRICT uniformly: an Instrument/Voice/Choirjob is never
    actually hard-deleted in this system (see Instrument's own docstring --
    its `active` flag exists specifically so it never has to be), so this
    is a defense-in-depth backstop for coreelement_service's own dependency
    check, not a live behavioral constraint in practice.

    Mixed into Booking, BookingLog, PerformancePosition and UserPosition.
    OrdinariumworkPosition deliberately does NOT use this mixin -- its
    domain excludes choirjobs entirely, so it declares instrument_id/
    voice_id directly instead of inheriting a column it must never
    populate.

    UUIDv7 as of the UUID-migration slice (2026-09), matching
    instruments/voices/choirjobs' own primary key type."""

    instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("instruments.id", ondelete="RESTRICT")
    )
    voice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voices.id", ondelete="RESTRICT")
    )
    choirjob_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("choirjobs.id", ondelete="RESTRICT")
    )
