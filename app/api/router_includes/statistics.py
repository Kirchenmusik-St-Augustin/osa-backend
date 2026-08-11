from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_guards import get_verified_user
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.statistics import StatisticsOutput
from app.services import statistics_service

statistics_router = APIRouter()


@statistics_router.get("")
def get_statistics(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(get_verified_user)],
) -> StatisticsOutput:
    """No permission gate beyond being logged in -- 1:1 Legacy's
    StatisticsController (no Policy/Gate exists for it at all)."""
    return statistics_service.get_statistics(db)
