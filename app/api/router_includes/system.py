from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db.models.user import User
from app.schemas.system import EnvironmentOutput
from app.services import system_service

system_router = APIRouter()


@system_router.get("/environment")
def get_environment(
    _current_user: Annotated[User, Depends(get_current_user)],
) -> EnvironmentOutput:
    """Any authenticated user may read this -- shown next to the frontend's
    own stage on the Statistics page so a mismatch between the two is
    visible at a glance. Requires only authentication, no permission gate."""
    return EnvironmentOutput(environment=system_service.get_app_environment())
