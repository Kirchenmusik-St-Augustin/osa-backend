from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.auth_guards import get_verified_user
from app.api.error_responses import field_errors_to_detail
from app.core.arq_pool import get_arq_pool
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
    """Reuses user_service.get_user() -- Legacy's ProfileController::show()
    renders the exact same `User\\Show` resource as
    System::UserController::show(), just scoped to the caller's own id."""
    return user_service.get_user(db, current_user.id)


def _update_profile_sync(
    db: Session, current_user: User, data: ProfileUpdateRequest
) -> tuple[User, bool]:
    return profile_service.update_profile(db, current_user, data)


@profile_router.put("")
async def update_profile(
    data: ProfileUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
    arq_pool: Annotated[ArqRedis, Depends(get_arq_pool)],
) -> UserResponse:
    """get_verified_user is declared before arq_pool on purpose: FastAPI
    resolves Depends() in declaration order, and a rejected/unverified
    session must not pay for creating/reusing the ARQ pool connection."""
    try:
        user, email_changed = await run_in_threadpool(
            _update_profile_sync, db, current_user, data
        )
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
    # THEIR OWN email gets a new verification mail (1:1 Legacy's
    # `sendEmailVerificationNotification()` call), unlike an admin editing
    # someone else's account. `user.email` is guaranteed non-None here --
    # ProfileUpdateRequest.email is a required EmailStr, not Optional.
    if email_changed and user.email is not None:
        verify_url = auth_service.build_verification_email_url(user)
        await arq_pool.enqueue_job(
            send_verification_email_task.__name__, user.email, verify_url
        )

    return user_service.get_user(db, user.id)
