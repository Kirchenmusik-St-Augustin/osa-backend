from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.auth_guards import require_permission
from app.core.scheduler import get_scheduled_jobs
from app.db.models.user import User
from app.schemas.scheduler import ScheduledJobOutput

scheduler_router = APIRouter()

_VIEW = Depends(require_permission("schedulerView"))


@scheduler_router.get("/jobs")
def list_scheduled_jobs(
    _current_user: Annotated[User, _VIEW],
) -> list[ScheduledJobOutput]:
    """Pure in-memory introspection of the running scheduler -- no DB
    session needed."""
    return [ScheduledJobOutput.model_validate(job) for job in get_scheduled_jobs()]
