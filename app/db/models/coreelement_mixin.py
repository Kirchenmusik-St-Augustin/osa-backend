import uuid

from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.timestamp_columns_mixin import TimestampColumns
from app.db.uuid_pk import uuid_pk


class CoreelementColumns(TimestampColumns):
    """Shared columns for the family of pure lookup tables
    (Instrument/Voice/Choirjob/Propriumelement -- all four are identical:
    id/name/order/timestamps only). Location mixes this in too but adds
    address/color (see location.py); Role keeps its own definition in
    role.py since it has label/description instead of a plain name-only
    shape.

    `order`'s DB column is `sort_order`: Postgres always requires `order` to
    be double-quoted as an identifier (a classic footgun), so every table
    built on this mixin (choirjobs/instruments/locations/propriumelements/
    voices) uses the safe name, as do Role's and Booking's own standalone
    `order` columns. The Python attribute/ORM-facing name stays `order` via
    mapped_column's explicit column-name argument (same alias pattern as
    SentEmail.mail_from, see sent_email.py), so every
    `.order`/`order=`/`order_by(<Model>.order)` call site across
    coreelement_service.py/performance_service.py/user_service.py/
    booking_service.py uses the Python name.

    `id` is a UUIDv7 primary key (server-generated via Postgres's native
    `uuidv7()`, see app.db.uuid_pk)."""

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(unique=True)
    order: Mapped[int] = mapped_column("sort_order", default=0)
