from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, get_verified_user
from app.db.database import get_db
from app.schemas.statistics import StatisticsOutput
from app.services import statistics_service
from app.services.permission_service import has_permission

statistics_router = APIRouter()


@statistics_router.get("")
def get_statistics(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthUser, Depends(get_verified_user)],
) -> StatisticsOutput:
    """Row counts for every logged-in member; the mail kill-switch status
    (how many mails were sent, how close the threshold is) only for those
    who may read the sent-mail log."""
    return statistics_service.get_statistics(
        db, include_email=has_permission(current_user, "sentEmailView")
    )
