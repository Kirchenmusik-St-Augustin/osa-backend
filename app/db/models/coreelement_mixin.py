from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class CoreelementColumns:
    """Shared columns for Legacy's `HasCoreelementFeatures` family of pure
    lookup tables (Instrument/Voice/Choirjob/Propriumelement -- see
    project_osa_legacy_domain_map memory: all four are 100% identical in
    the Legacy schema, id/name/order/timestamps only). Location mixes this
    in too but adds address/color (see location.py); Role predates this
    slice (Schritt 2 Auth) and keeps its own definition in role.py since it
    already has label/description instead of a plain name-only shape."""

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime())
