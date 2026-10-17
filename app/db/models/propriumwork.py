from sqlalchemy import Index, UniqueConstraint

from app.db.database import Base
from app.db.models.repertoire_work_mixin import RepertoireWorkColumns


class Propriumwork(RepertoireWorkColumns, Base):
    __tablename__ = "propriumworks"
    __table_args__ = (
        UniqueConstraint("name", "artist_id"),
        Index("propriumworks_artist_id_index", "artist_id"),
    )
