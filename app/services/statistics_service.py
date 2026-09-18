from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core import mailer
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.propriumwork import Propriumwork
from app.db.models.score import Score
from app.db.models.user import User
from app.schemas.statistics import StatisticsEmailOutput, StatisticsOutput

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _count(db: Session, model: type) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def get_statistics(db: Session) -> StatisticsOutput:
    """Six raw row counts. `users` excludes soft-deleted rows."""
    users = db.execute(
        select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    ).scalar_one()
    kill_switch = mailer.get_kill_switch_status(db)
    return StatisticsOutput(
        users=users,
        performances=_count(db, Performance),
        ordinariumworks=_count(db, Ordinariumwork),
        propriumworks=_count(db, Propriumwork),
        scores=_count(db, Score),
        email=StatisticsEmailOutput(
            active=kill_switch.active,
            period_days=kill_switch.period_days,
            threshold=kill_switch.threshold,
            sent=kill_switch.sent,
        ),
    )
