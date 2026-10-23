import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, require_permission
from app.api.query_params import PageDep, SearchTerm
from app.db.database import get_db
from app.schemas.base import IdLabelOutput
from app.schemas.booking import PerformanceShortOutput
from app.schemas.pagination import Page
from app.schemas.user import UserFormOptionsOutput, UserRequest, UserResponse
from app.services import booking_service, user_service

user_router = APIRouter()

_MAINTAIN = Depends(require_permission("userMaintain"))

# "/search" and "/form-options" must be registered before "/{user_id}" --
# FastAPI/Starlette try routes in registration order, and {user_id} would
# otherwise greedily match these literal segments first, then fail Pydantic
# int coercion instead of dispatching correctly.


@user_router.get("/search")
def search_users(
    q: SearchTerm,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _MAINTAIN],
) -> list[IdLabelOutput]:
    users = user_service.search_users(db, q)
    return [user_service.to_search_result(user) for user in users]


@user_router.get("/form-options")
def get_form_options(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _MAINTAIN],
) -> UserFormOptionsOutput:
    return user_service.get_form_options(db)


@user_router.get("/{user_id}")
def get_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _MAINTAIN],
) -> UserResponse:
    return user_service.get_user(db, user_id)


@user_router.get("/{user_id}/requests-and-bookings")
def get_requests_and_bookings(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _MAINTAIN],
    page: PageDep,
) -> Page[PerformanceShortOutput]:
    """Admin-side counterpart to /support/requests-and-bookings (the Show
    page's link), backed by the same generic booking_service function,
    scoped to an arbitrary `user_id` instead of the caller. `upcoming_only=
    False` here (unlike the Selfadmin caller): the admin sees the user's
    ALL-history (see get_upcoming_requests_and_bookings_for_user's
    docstring)."""
    user_service.get_user(db, user_id)
    return Page.of(
        booking_service.get_upcoming_requests_and_bookings_for_user(
            db, user_id, page, upcoming_only=False
        ),
        page,
    )


@user_router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    data: UserRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthUser, _MAINTAIN],
) -> UserResponse:
    return user_service.create_user(db, data, current_user)


@user_router.put("/{user_id}")
def update_user(
    user_id: uuid.UUID,
    data: UserRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthUser, _MAINTAIN],
) -> UserResponse:
    return user_service.update_user(db, user_id, data, current_user)


@user_router.delete("/{user_id}")
def delete_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[AuthUser, _MAINTAIN],
) -> dict[str, str]:
    user_service.delete_user(db, user_id)
    return {"status": "ok", "message": "Benutzerkonto wurde gelöscht."}
