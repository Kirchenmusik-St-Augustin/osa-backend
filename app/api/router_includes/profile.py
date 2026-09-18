from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import get_verified_user
from app.api.error_responses import field_errors_to_detail
from app.api.job_queue import JobQueue, get_job_queue
from app.core.redacted import Redacted
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.profile import ProfileUpdateRequest
from app.schemas.user import UserResponse
from app.services import auth_service, profile_service, user_service
from app.services.profile_service import (
    ProfileValidationError,
    WrongCurrentPasswordError,
)
from app.worker.tasks import send_verification_email_task

profile_router = APIRouter()

_WRONG_PASSWORD_DETAIL = "Das bestehende Passwort ist falsch."  # noqa: S105 -- user-facing error text, not a credential


@profile_router.get("")
def get_profile(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> UserResponse:
    """Reuses user_service.get_user() -- the same resource as the admin-side
    user detail, just scoped to the caller's own id."""
    return user_service.get_user(db, current_user.id)


@profile_router.put("")
def update_profile(
    data: ProfileUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> UserResponse:
    """get_verified_user is declared before job_queue on purpose, see
    get_job_queue."""
    try:
        user, email_changed = profile_service.update_profile(db, current_user, data)
    except WrongCurrentPasswordError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail([("auth_password", _WRONG_PASSWORD_DETAIL)]),
        ) from None
    except ProfileValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None

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
