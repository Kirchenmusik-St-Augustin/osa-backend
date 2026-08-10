from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth_guards import require_permission
from app.api.error_responses import field_errors_to_detail
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.booking import PerformanceShortOutput
from app.schemas.user import (
    UserFormOptionsOutput,
    UserRequest,
    UserResponse,
    UserSearchResultOutput,
)
from app.services import booking_service, user_service
from app.services.user_service import (
    AdministratorProtectedError,
    UserInUseError,
    UserNotFoundError,
    UserValidationError,
)

user_router = APIRouter()

_MAINTAIN = Depends(require_permission("userMaintain"))
_NOT_FOUND_DETAIL = "Nicht gefunden."
_ADMINISTRATOR_PROTECTED_DETAIL = (
    "Administrator-Konten können hier nicht bearbeitet oder gelöscht werden."
)
_IN_USE_DETAIL = (
    "Das Benutzerkonto kann nicht gelöscht werden, da es noch in Verwendung ist."
)

# "/search" and "/form-options" must be registered before "/{user_id}" --
# FastAPI/Starlette try routes in registration order, and {user_id} would
# otherwise greedily match these literal segments first, then fail Pydantic
# int coercion instead of dispatching correctly.


@user_router.get("/search")
def search_users(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[UserSearchResultOutput]:
    users = user_service.search_users(db, q)
    return [
        UserSearchResultOutput(id=user.id, label=f"{user.surname}, {user.givenname}")
        for user in users
    ]


@user_router.get("/form-options")
def get_form_options(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> UserFormOptionsOutput:
    return user_service.get_form_options(db)


@user_router.get("/{user_id}")
def get_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> UserResponse:
    try:
        return user_service.get_user(db, user_id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None


@user_router.get("/{user_id}/requests-and-bookings")
def get_requests_and_bookings(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> list[PerformanceShortOutput]:
    """Admin-side counterpart to /support/requests-and-bookings (Schritt 7,
    Selfadmin) -- Legacy's `.../users/{user}/requestsAndBookings` link on
    the Show page, backed by the same generic booking_service function,
    scoped to an arbitrary `user_id` instead of the caller. `upcoming_only=
    False` here (unlike the Selfadmin caller) -- Legacy's
    `System\\UserController::requestsAndBookings()` calls the model method
    with its bare, ALL-history default (see
    get_upcoming_requests_and_bookings_for_user's docstring)."""
    try:
        user_service.get_user(db, user_id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    return booking_service.get_upcoming_requests_and_bookings_for_user(
        db, user_id, upcoming_only=False
    )


@user_router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _MAINTAIN],
) -> UserResponse:
    try:
        return user_service.create_user(db, data, current_user)
    except UserValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@user_router.put("/{user_id}")
def update_user(
    user_id: int,
    data: UserRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, _MAINTAIN],
) -> UserResponse:
    try:
        return user_service.update_user(db, user_id, data, current_user)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except AdministratorProtectedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(
                [("general", _ADMINISTRATOR_PROTECTED_DETAIL)]
            ),
        ) from None
    except UserValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(exc.errors),
        ) from None


@user_router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, _MAINTAIN],
) -> dict[str, str]:
    try:
        user_service.delete_user(db, user_id)
    except UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL
        ) from None
    except AdministratorProtectedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail(
                [("general", _ADMINISTRATOR_PROTECTED_DETAIL)]
            ),
        ) from None
    except UserInUseError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=field_errors_to_detail([("general", _IN_USE_DETAIL)]),
        ) from None
    return {"status": "ok", "message": "Benutzerkonto wurde gelöscht."}
