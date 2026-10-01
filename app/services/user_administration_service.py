from typing import TYPE_CHECKING

from sqlalchemy import exists, func, select

from app.core.security import generate_random_password, get_password_hash
from app.db.models.booking import Booking
from app.db.models.booking_log import BookingLog
from app.db.models.booking_request import BookingRequest
from app.db.models.user import User
from app.services.errors import GeneralValidationError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

_SEARCH_RESULT_LIMIT = 20

# Tables whose rows are business history of a user (bookings, requests and the
# booking audit log). Their FKs either RESTRICT or would silently anonymize
# the history on delete, so any such row keeps the account from being purged.
_HISTORY_MODELS = (Booking, BookingRequest, BookingLog)


class UserAdministrationNotFoundError(Exception):
    """Raised when `user_id` doesn't exist at all -- this domain always
    includes soft-deleted users, unlike user_service's soft-delete-aware
    lookups."""


class SelfTargetError(Exception):
    """set_random_password() targeting the acting administrator
    themselves."""


class UserNotDeletedError(GeneralValidationError):
    """purge_user() targeting an account that has not been soft-deleted first."""

    def __init__(self) -> None:
        super().__init__(
            "Nur gelöschte Benutzerkonten können dauerhaft gelöscht werden."
        )


class UserHasHistoryError(GeneralValidationError):
    """purge_user() blocked by bookings, requests or booking log entries."""

    def __init__(self) -> None:
        super().__init__(
            "Das Benutzerkonto kann nicht dauerhaft gelöscht werden, da noch "
            "Buchungen oder sonstige Verweise existieren."
        )


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


def _has_history(db: Session, user_id: uuid.UUID) -> bool:
    return any(
        db.execute(select(exists().where(model.user_id == user_id))).scalar_one()
        for model in _HISTORY_MODELS
    )


def is_purgeable(db: Session, user: User) -> bool:
    """A soft-deleted account without any booking history can be removed for
    good; everything else on the account (roles, positions, tokens, OAuth2
    bindings) is cascaded away by the database."""
    return user.deleted_at is not None and not _has_history(db, user.id)


def purge_user(db: Session, user_id: uuid.UUID) -> None:
    user = _get_or_404(db, user_id)
    if user.deleted_at is None:
        raise UserNotDeletedError
    if _has_history(db, user.id):
        raise UserHasHistoryError

    db.delete(user)
    db.commit()
