from sqlalchemy import CheckConstraint, Index, UniqueConstraint

from app.db.database import Base
from app.db.models.repertoire_work_mixin import RepertoireWorkColumns


class Ordinariumwork(RepertoireWorkColumns, Base):
    __tablename__ = "ordinariumworks"
    __table_args__ = (
        UniqueConstraint("name", "artist_id"),
        Index("ordinariumworks_artist_id_index", "artist_id"),
        CheckConstraint(
            "duration IS NULL OR duration BETWEEN 1 AND 999",
            name="ordinariumworks_duration_check",
        ),
    )
