from sqlalchemy import UniqueConstraint

from app.db.database import Base
from app.db.models.repertoire_work_mixin import RepertoireWorkColumns


class Ordinariumwork(RepertoireWorkColumns, Base):
    __tablename__ = "ordinariumworks"
    __table_args__ = (UniqueConstraint("name", "artist_id"),)
