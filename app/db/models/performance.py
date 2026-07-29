from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Performance(Base):
    """Mirrors legacy `performances` exactly (Phase 1). `artist_id` here is
    the CONDUCTOR (Dirigent), not a composer -- a separate, nullable
    reference into the same `artists` table used by Ordinariumwork/
    Propriumwork's composer `artist_id`. `location_id`/`ordinariumwork_id`/
    `artist_id` are plain ints, not ForeignKeys, per Phase 1's no-FK
    structural parity (see repertoire_work_mixin.py for the same reasoning).
    `choirjob_defaultfee`/`instrument_defaultfee`/`voice_defaultfee` are
    NOT the fee actually paid to a booked musician (chosen per-booking on
    the Cast page, Schritt 6) -- they're placeholder billing rates used
    only to price still-unfilled slots in the Abrechnung (see
    project_osa_performance_domain_research memory)."""

    __tablename__ = "performances"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule: Mapped[datetime] = mapped_column(DateTime())
    location_id: Mapped[int]
    ordinariumwork_id: Mapped[int]
    artist_id: Mapped[int | None]
    description: Mapped[str | None]
    choirjob_defaultfee: Mapped[int] = mapped_column(default=35)
    instrument_defaultfee: Mapped[int] = mapped_column(default=60)
    voice_defaultfee: Mapped[int] = mapped_column(default=110)
    extracost_amount: Mapped[int | None]
    extracost_description: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
