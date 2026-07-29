from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Instrument(CoreelementColumns, Base):
    __tablename__ = "instruments"
