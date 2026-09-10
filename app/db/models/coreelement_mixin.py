from datetime import datetime

from sqlalchemy import DateTime, FetchedValue, func
from sqlalchemy.orm import Mapped, mapped_column


class CoreelementColumns:
    """Shared columns for Legacy's `HasCoreelementFeatures` family of pure
    lookup tables (Instrument/Voice/Choirjob/Propriumelement -- all four
    are 100% identical in the Legacy schema, id/name/order/timestamps
    only). Location mixes this
    in too but adds address/color (see location.py); Role predates this
    slice (Schritt 2 Auth) and keeps its own definition in role.py since it
    already has label/description instead of a plain name-only shape.

    `order`'s DB column is `sort_order` as of the Quick-Wins hardening
    slice (2026-09) -- Postgres always requires `order` to be
    double-quoted as an identifier (a classic footgun), so every table
    built on this mixin (choirjobs/instruments/locations/propriumelements/
    voices) got the same treatment Role's and Booking's own standalone
    `order` columns got in the same slice. The Python attribute/ORM-facing
    name stays `order` via mapped_column's explicit column-name argument
    (same alias pattern as SentEmail.mail_from, see sent_email.py) --
    every existing `.order`/`order=`/`order_by(<Model>.order)` call site
    across coreelement_service.py/performance_service.py/user_service.py/
    booking_service.py is untouched.

    `created_at`/`updated_at` are TIMESTAMPTZ as of the TIMESTAMPTZ +
    audit-trigger hardening slice (2026-09): `created_at` is populated by
    the database's own DEFAULT now(), `updated_at` by the shared
    set_updated_at() BEFORE UPDATE trigger registered on every table built
    on this mixin -- neither is ever assigned from Python anymore."""

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    order: Mapped[int] = mapped_column("sort_order", default=0)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
