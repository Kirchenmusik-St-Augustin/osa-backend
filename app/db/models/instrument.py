from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Instrument(CoreelementColumns, Base):
    """`active` is an osa-fastapi-vue-only addition, not part of the
    original Legacy schema (see CLAUDE.md section 3's Phase 1 boundary --
    this is a deliberate, User-approved exception, 2026-08-21). Lets an
    instrument be hidden from "add a new position" pickers without
    breaking historical bookings/booking_logs/performance_positions/
    ordinariumwork_positions/user_positions references, which is why no
    row ever gets DELETEd for this (the Legacy schema has zero FK
    constraints, so a DELETE wouldn't even fail -- it would just orphan
    those references)."""

    __tablename__ = "instruments"

    active: Mapped[bool] = mapped_column(default=True)
