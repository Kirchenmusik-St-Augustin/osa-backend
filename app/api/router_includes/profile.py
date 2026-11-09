from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, get_verified_user
from app.api.deps import get_current_session_id
from app.api.job_queue import JobQueue, get_job_queue
from app.api.rate_limiting import (
    MAIL_ACTION_LIMIT,
    MAIL_ACTION_SCOPE,
    rate_limited_per_user,
)
from app.core.redacted import Redacted
from app.db.database import get_db
from app.schemas.profile import ProfileUpdateRequest
from app.schemas.user import UserResponse
from app.services import auth_service, profile_service, user_service
from app.worker.tasks import send_verification_email_task

profile_router = APIRouter()


@profile_router.get("")
def get_profile(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthUser, Depends(get_verified_user)],
) -> UserResponse:
    """Reuses user_service.get_user() -- the same resource as the admin-side
    user detail, just scoped to the caller's own id."""
    return user_service.get_user(db, current_user.id)


@profile_router.put("")
@rate_limited_per_user(MAIL_ACTION_LIMIT, MAIL_ACTION_SCOPE)
def update_profile(
    request: Request,  # noqa: ARG001
    data: ProfileUpdateRequest,
    *,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthUser, Depends(get_verified_user)],
    session_id: Annotated[str, Depends(get_current_session_id)],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> UserResponse:
    """get_verified_user is declared before job_queue on purpose, see
    get_job_queue. The session id keeps the caller logged in when a password
    change revokes all other sessions."""
    user, email_changed = profile_service.update_profile(
        db, current_user, data, current_session_id=session_id
    )

    # Asymmetric with user_service.update_user() by design: a user changing
    # THEIR OWN email gets a new verification mail, unlike an admin editing
    # someone else's account. `user.email` is guaranteed non-None here --
    # ProfileUpdateRequest.email is a required EmailStr, not Optional.
    if email_changed and user.email is not None:
        verify_url = auth_service.build_verification_email_url(user)
        job_queue.enqueue(
            send_verification_email_task, user.email, Redacted(verify_url)
        )

    return user_service.get_user(db, user.id)
