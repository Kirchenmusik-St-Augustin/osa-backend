from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import generate_random_password, get_password_hash
from app.db.models.user import User

_SEARCH_RESULT_LIMIT = 20


class UserAdministrationNotFoundError(Exception):
    """Raised when `user_id` doesn't exist at all -- this domain always
    operates `withTrashed()` (1:1 Legacy's UserAdministrationController
    routes), unlike user_service's soft-delete-aware lookups."""


class SelfTargetError(Exception):
    """set_random_password() targeting the acting administrator themselves
    -- 1:1 Legacy's `abort_if(auth()->user()->id === $user->id, 403, ...)`
    in UserAdministrationController::setPassword()."""


def search_users_including_deleted(db: Session, query: str) -> Sequence[User]:
    """1:1 Legacy's `User::search($q, true)` -- real indexed DB query (not
    Legacy's in-memory-filter anti-pattern), deliberately including
    soft-deleted users (Legacy's `withTrashed` argument)."""
    words = [word for word in query.lower().split() if word]
    if not words:
        return []

    combined_name = func.lower(User.surname + ", " + User.givenname)
    stmt = (
        select(User)
        .where(*[combined_name.like(f"%{word}%") for word in words])
        .order_by(User.surname, User.givenname)
        .limit(_SEARCH_RESULT_LIMIT)
    )
    return db.execute(stmt).scalars().all()


def list_deleted_users(db: Session) -> Sequence[User]:
    """1:1 Legacy's `User::onlyTrashed()->get()`, shown directly on the
    initial (queryless) Search page load."""
    stmt = (
        select(User)
        .where(User.deleted_at.is_not(None))
        .order_by(User.surname, User.givenname)
    )
    return db.execute(stmt).scalars().all()


def _get_or_404(db: Session, user_id: int) -> User:
    result = db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserAdministrationNotFoundError
    return user


def get_user(db: Session, user_id: int) -> User:
    return _get_or_404(db, user_id)


def restore_user(db: Session, user_id: int) -> User:
    user = _get_or_404(db, user_id)
    user.deleted_at = None
    db.commit()
    return user


def unlock_user(db: Session, user_id: int) -> User:
    user = _get_or_404(db, user_id)
    user.auth_locked = False
    db.commit()
    return user


def set_random_password(
    db: Session, user_id: int, current_user_id: int
) -> tuple[User, str]:
    """Generates a one-time password, shown ONCE in the response -- never
    logged, never emailed (1:1 Legacy, which has no mail trigger for this
    action either)."""
    user = _get_or_404(db, user_id)
    if user_id == current_user_id:
        raise SelfTargetError

    plain_password = generate_random_password()
    user.auth_password = get_password_hash(plain_password)
    db.commit()
    return user, plain_password
