from app.db.database import Base
from app.db.models.coreelement_mixin import CoreelementColumns


class Voice(CoreelementColumns, Base):
    __tablename__ = "voices"
