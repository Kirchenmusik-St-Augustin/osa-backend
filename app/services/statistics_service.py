from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import mailer
from app.db.models.ordinariumwork import Ordinariumwork
from app.db.models.performance import Performance
from app.db.models.propriumwork import Propriumwork
from app.db.models.user import User
from app.schemas.statistics import StatisticsEmailOutput, StatisticsOutput


def _count(db: Session, model: type) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def get_statistics(db: Session) -> StatisticsOutput:
    """1:1 Legacy's `StatisticsController::statistics()` -- five raw
    `Model::count()` calls (see StatisticsOutput's docstring for the
    deliberately-missing sixth, Scores). `users` excludes soft-deleted
    rows, matching Legacy's `User::count()` (default Eloquent scope, no
    `withTrashed()`)."""
    users = db.execute(
        select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    ).scalar_one()
    kill_switch = mailer.get_kill_switch_status(db)
    return StatisticsOutput(
        users=users,
        performances=_count(db, Performance),
        ordinariumworks=_count(db, Ordinariumwork),
        propriumworks=_count(db, Propriumwork),
        email=StatisticsEmailOutput(
            active=kill_switch.active,
            period_days=kill_switch.period_days,
            threshold=kill_switch.threshold,
            sent=kill_switch.sent,
        ),
    )
