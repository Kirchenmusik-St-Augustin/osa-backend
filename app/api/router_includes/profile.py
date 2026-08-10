from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.error_responses import field_errors_to_detail
from app.core import mailer
from app.core.config import get_settings, require_setting
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.profile import ProfileUpdateRequest
from app.schemas.user import UserResponse
from app.services import auth_service, profile_service, user_service
from app.services.profile_service import (
    ProfileValidationError,
    WrongCurrentPasswordError,
)

profile_router = APIRouter()

_WRONG_PASSWORD_DETAIL = "Das bestehende Passwort ist falsch."  # noqa: S105 -- user-facing error text, not a credential


@profile_router.get("")
def get_profile(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Reuses user_service.get_user() -- Legacy's ProfileController::show()
    renders the exact same `User\\Show` resource as
    System::UserController::show(), just scoped to the caller's own id."""
    return user_service.get_user(db, current_user.id)


@profile_router.put("")
def update_profile(
    data: ProfileUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
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
    # THEIR OWN email gets a new verification mail (1:1 Legacy's
    # `sendEmailVerificationNotification()` call), unlike an admin editing
    # someone else's account. `user.email` is guaranteed non-None here --
    # ProfileUpdateRequest.email is a required EmailStr, not Optional.
    if email_changed and user.email is not None:
        settings = get_settings()
        base_url = require_setting(
            settings.frontend_verify_email_url, "FRONTEND_VERIFY_EMAIL_URL"
        )
        token = auth_service.build_email_verification_token(user)
        verify_url = f"{base_url}?{urlencode({'token': token})}"
        background_tasks.add_task(
            mailer.send_verification_email, user.email, verify_url
        )

    return user_service.get_user(db, user.id)
