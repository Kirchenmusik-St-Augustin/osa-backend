from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Fee(Base):
    """Mirrors legacy `fees` exactly (Phase 1). A standalone billing-rate
    lookup table, administered through its own dedicated Legacy controller
    (`Content/System/FeeController`, not the generic Coreelement mechanism)
    -- unlike Instrument/Voice/Choirjob/Location/Role/Propriumelement, `fees`
    has no `order` column, so it deliberately does NOT use
    CoreelementColumns (see project_osa_legacy_domain_map memory). Bookings
    copy a Fee's `amount` into `bookings.fee`/`booking_logs.fee` as a plain
    integer at booking time -- there is no FK from either table back to
    `fees.id`, so deleting a Fee never orphans a booking."""

    __tablename__ = "fees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    amount: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
