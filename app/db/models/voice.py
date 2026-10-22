from sqlalchemy import true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Voice(CoreelementColumns, Base):
    """`active` lets a voice be hidden from "add a new position" pickers
    without breaking historical bookings/booking_logs/performance_positions/
    ordinariumwork_positions/user_positions references, which is why voices
    are archived rather than DELETEd (same reasoning as Instrument and
    Choirjob)."""

    __tablename__ = "voices"

    active: Mapped[bool] = mapped_column(default=True, server_default=true())
