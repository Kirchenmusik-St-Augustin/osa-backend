from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Location(CoreelementColumns, Base):
    """Only Coreelement-family model with extra columns beyond
    name/order/timestamps -- `address` is nullable in the Legacy schema
    even though the Legacy form makes it required (application-level
    constraint only, see coreelement_service's per-type FieldSpec)."""

    __tablename__ = "locations"

    address: Mapped[str | None]
    color: Mapped[str] = mapped_column(default="000000")
