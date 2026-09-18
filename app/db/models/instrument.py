from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Instrument(CoreelementColumns, Base):
    """`active` lets an instrument be hidden from "add a new position"
    pickers without breaking historical bookings/booking_logs/
    performance_positions/ordinariumwork_positions/user_positions
    references, which is why instruments are archived rather than
    DELETEd."""

    __tablename__ = "instruments"

    active: Mapped[bool] = mapped_column(default=True)
