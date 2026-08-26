from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.human_names import normalize_givenname, normalize_surname
from app.core.security import get_password_hash, verify_password
from app.db.models.user import User
from app.schemas.profile import ProfileUpdateRequest
from app.schemas.validators import PASSWORD_POLICY_MESSAGE


class WrongCurrentPasswordError(Exception):
    """`auth_password` doesn't match the user's actual current password --
    1:1 Legacy's ValidAuthPassword rule ("Das bestehende Passwort ist
    falsch.")."""


class ProfileValidationError(Exception):
    """Field-level validation failures, mirroring Legacy's UpdateRequest
    error bag -- 1:1 user_service.UserValidationError pattern."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Profile validation failed")


def _name_combo_taken(
    db: Session, surname: str, givenname: str, exclude_id: int
) -> bool:
    stmt = select(User.id).where(
        User.surname == surname, User.givenname == givenname, User.id != exclude_id
    )
    return db.execute(stmt).scalar_one_or_none() is not None


def _email_taken(db: Session, email: str, exclude_id: int) -> bool:
    stmt = select(User.id).where(User.email == email, User.id != exclude_id)
    return db.execute(stmt).scalar_one_or_none() is not None


def update_profile(
    db: Session, user: User, data: ProfileUpdateRequest
) -> tuple[User, bool]:
    """Returns (user, email_changed) -- the router decides whether to send
    a new verification mail (BackgroundTasks needs a request context this
    service deliberately doesn't have), this stays framework-agnostic.

    Order mirrors Legacy: re-auth check first (ValidAuthPassword), then the
    two composite-unique checks (`Rule::unique()->ignore(self)`), then the
    "new password differs from the current one" sub-rule that only
    ValidNewPassword's `auth()->check()` branch can run -- schema-level
    validators have no DB access, see app.schemas.profile."""
    if not verify_password(data.auth_password, user.auth_password):
        raise WrongCurrentPasswordError

    surname = normalize_surname(data.surname)
    givenname = normalize_givenname(data.givenname)

    errors: list[tuple[str, str]] = []
    if _name_combo_taken(db, surname, givenname, exclude_id=user.id):
        msg = "Die Kombination von Vor- und Nachname ist vergeben."
        errors.append(("surname", msg))
        errors.append(("givenname", msg))
    if _email_taken(db, data.email, exclude_id=user.id):
        errors.append(("email", "Diese E-Mail-Adresse ist bereits vergeben."))
    if (
        data.change_password
        and data.password is not None
        and verify_password(data.password, user.auth_password)
    ):
        errors.append(("password", PASSWORD_POLICY_MESSAGE))
    if errors:
        raise ProfileValidationError(errors)

    # Raw string comparison, not case-normalized -- 1:1 Legacy's
    # `auth()->user()->email !== $validated['email']`.
    email_changed = data.email != user.email

    if data.change_password and data.password:
        user.auth_password = get_password_hash(data.password)
    user.givenname = givenname
    user.surname = surname
    user.phone = data.phone
    user.email = data.email
    if email_changed:
        user.email_verified_at = None
    user.updated_at = datetime.now(UTC)
    db.commit()
    return user, email_changed
