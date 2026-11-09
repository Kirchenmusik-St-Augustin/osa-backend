from sqlalchemy import true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Choirjob(CoreelementColumns, Base):
    """`active` lets a choir job be hidden from "add a new position" pickers
    without breaking historical bookings/booking_logs/performance_positions/
    user_positions references, which is why choir jobs are archived rather
    than DELETEd (same reasoning as Instrument and Voice)."""

    __tablename__ = "choirjobs"

    active: Mapped[bool] = mapped_column(default=True, server_default=true())
