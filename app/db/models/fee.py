import uuid

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class Fee(TimestampColumns, Base):
    """Standalone billing-rate lookup table. `amount >= 0` is enforced both
    at the Pydantic layer (FeeRequest.amount: Field(ge=0, le=999)) and by a
    database CHECK constraint, so no non-API write path can store a
    negative amount.

    Administered through its own dedicated service (not the generic
    Coreelement mechanism) -- unlike Instrument/Voice/Choirjob/
    Location/Role/Propriumelement, `fees` has no `order` column, so it
    deliberately does NOT use CoreelementColumns. Bookings copy a Fee's
    `amount` into `bookings.fee`/`booking_logs.fee` as a plain integer at
    booking time -- there is no FK from either table back to `fees.id`, so
    deleting a Fee never orphans a booking."""

    __tablename__ = "fees"
    __table_args__ = (CheckConstraint("amount >= 0", name="fees_amount_check"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(unique=True)
    amount: Mapped[int] = mapped_column(default=0)
