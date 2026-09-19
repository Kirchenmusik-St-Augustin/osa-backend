from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.security import generate_random_password, get_password_hash
from app.db.models.user import User

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

_SEARCH_RESULT_LIMIT = 20


class UserAdministrationNotFoundError(Exception):
    """Raised when `user_id` doesn't exist at all -- this domain always
    includes soft-deleted users, unlike user_service's soft-delete-aware
    lookups."""


class SelfTargetError(Exception):
    """set_random_password() targeting the acting administrator
    themselves."""


def search_users_including_deleted(db: Session, query: str) -> Sequence[User]:
    """Filtered in the database (not in memory), deliberately including
    soft-deleted users."""
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
    """All soft-deleted users, shown directly on the initial (queryless)
    Search page load."""
    stmt = (
        select(User)
        .where(User.deleted_at.is_not(None))
        .order_by(User.surname, User.givenname)
    )
    return db.execute(stmt).scalars().all()


def _get_or_404(db: Session, user_id: uuid.UUID) -> User:
    result = db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UserAdministrationNotFoundError
    return user


def get_user(db: Session, user_id: uuid.UUID) -> User:
    return _get_or_404(db, user_id)


def restore_user(db: Session, user_id: uuid.UUID) -> User:
    user = _get_or_404(db, user_id)
    user.deleted_at = None
    db.commit()
    return user


def unlock_user(db: Session, user_id: uuid.UUID) -> User:
    user = _get_or_404(db, user_id)
    user.auth_locked = False
    db.commit()
    return user


def set_random_password(
    db: Session, user_id: uuid.UUID, current_user_id: uuid.UUID
) -> tuple[User, str]:
    """Generates a one-time password, shown ONCE in the response -- never
    logged, never emailed."""
    user = _get_or_404(db, user_id)
    if user_id == current_user_id:
        raise SelfTargetError

    plain_password = generate_random_password()
    user.auth_password = get_password_hash(plain_password)
    db.commit()
    return user, plain_password
