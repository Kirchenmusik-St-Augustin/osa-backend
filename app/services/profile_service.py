from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.human_names import normalize_givenname, normalize_surname
from app.core.security import get_password_hash, verify_password
from app.db.models.user import User
from app.schemas.validators import PASSWORD_UNCHANGED_MESSAGE
from app.services.errors import (
    DomainValidationError,
    FieldError,
    GeneralValidationError,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from app.schemas.profile import ProfileUpdateRequest

_WRONG_PASSWORD_DETAIL = "Das bestehende Passwort ist falsch."  # noqa: S105 -- user-facing error text, not a credential


class WrongCurrentPasswordError(GeneralValidationError):
    """`auth_password` doesn't match the user's actual current password."""

    def __init__(self) -> None:
        super().__init__(_WRONG_PASSWORD_DETAIL, field="auth_password")


class ProfileValidationError(DomainValidationError):
    """Field-level validation failures, one (field, message) pair per
    failing field -- same pattern as user_service.UserValidationError."""


def _name_combo_taken(
    db: Session, surname: str, givenname: str, exclude_id: uuid.UUID
) -> bool:
    stmt = select(User.id).where(
        User.surname == surname, User.givenname == givenname, User.id != exclude_id
    )
    return db.execute(stmt).scalar_one_or_none() is not None


def _email_taken(db: Session, email: str, exclude_id: uuid.UUID) -> bool:
    stmt = select(User.id).where(User.email == email, User.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def update_profile(
    db: Session, user: User, data: ProfileUpdateRequest
) -> tuple[User, bool]:
    """Returns (user, email_changed) -- the router decides whether to enqueue
    a new verification mail (job queueing needs a request context this
    service deliberately doesn't have), this stays framework-agnostic.

    Order: re-auth check (current password) first, then the two
    composite-unique checks (ignoring the caller's own row), then the "new
    password differs from the current one" sub-rule -- schema-level
    validators have no DB access, see app.schemas.profile."""
    if not verify_password(data.auth_password, user.auth_password):
        raise WrongCurrentPasswordError

    surname = normalize_surname(data.surname)
    givenname = normalize_givenname(data.givenname)

    errors: list[FieldError] = []
    if _name_combo_taken(db, surname, givenname, exclude_id=user.id):
        msg = "Die Kombination von Vor- und Nachname ist vergeben."
        errors.append(FieldError("surname", msg))
        errors.append(FieldError("givenname", msg))
    if _email_taken(db, data.email, exclude_id=user.id):
        errors.append(FieldError("email", "Diese E-Mail-Adresse ist bereits vergeben."))
    if (
        data.change_password
        and data.password is not None
        and verify_password(data.password, user.auth_password)
    ):
        errors.append(FieldError("password", PASSWORD_UNCHANGED_MESSAGE))
    if errors:
        raise ProfileValidationError(errors)

    # Raw string comparison, not case-normalized.
    email_changed = data.email != user.email

    if data.change_password and data.password:
        user.auth_password = get_password_hash(data.password)
    user.givenname = givenname
    user.surname = surname
    user.phone = data.phone
    user.email = data.email
    if email_changed:
        user.email_verified_at = None
    db.commit()
    return user, email_changed
