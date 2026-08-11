from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class OrdinariumworkPosition(Base):
    """Pivot row: which Instrument/Voice an Ordinariumwork needs, and in
    what quantity (e.g. "2x Violine, 4x Sopran"). Legacy's `position_type`/
    `position_id` polymorphy (Relation::morphMap 'instruments'/'voices'/
    'choirjobs') is deliberately restricted to 'instruments'/'voices' ONLY
    here -- confirmed by the real CHECK constraint AND by live data (1677
    rows, zero 'choirjobs' -- see project_osa_migration_plan memory,
    Schritt 4). No standalone controller/routes in Legacy: managed
    entirely through Ordinariumwork's own create/update ("setup" payload),
    never directly -- same here (see ordinariumwork_service.py)."""

    __tablename__ = "ordinariumwork_positions"
    __table_args__ = (
        UniqueConstraint("ordinariumwork_id", "position_type", "position_id"),
        CheckConstraint("position_type IN ('instruments', 'voices')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ordinariumwork_id: Mapped[int]
    position_type: Mapped[str]
    position_id: Mapped[int]
    quantity: Mapped[int]
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
