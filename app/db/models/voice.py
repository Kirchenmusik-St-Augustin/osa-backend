from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Voice(CoreelementColumns, Base):
    """See Instrument's docstring -- `active` is the same osa-fastapi-vue-
    only addition, applied identically to all three position-referenced
    Coreelement types (Instrument/Voice/Choirjob)."""

    __tablename__ = "voices"

    active: Mapped[bool] = mapped_column(default=True)
