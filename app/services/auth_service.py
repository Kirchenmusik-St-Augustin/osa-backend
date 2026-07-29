from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NoReturn, overload

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings, require_setting
from app.core.human_names import normalize_givenname, normalize_surname
from app.core.security import (
    ALGORITHM,
    REFRESH_TOKEN_LIFETIME_DAYS,
    SECRET_KEY,
    SESSION_IDLE_TIMEOUT_MINUTES,
    InvalidVerificationTokenError,
    create_access_token,
    create_email_verification_token,
    decode_email_verification_token,
    generate_refresh_secret,
    generate_reset_token,
    get_password_hash,
    hash_email_for_verification,
    hash_refresh_secret,
    hash_reset_token,
    verify_password,
    verify_refresh_secret,
    verify_reset_token,
)
from app.db.models.auth_log import AuthLog
from app.db.models.oauth2_binding import Oauth2Binding
from app.db.models.password_reset_token import PasswordResetToken
from app.db.models.personal_access_token import PersonalAccessToken
from app.db.models.user import User
from app.schemas.auth import RegisterRequest

# Mirrors Legacy's StoreRequest::ensureIsNotRateLimited() (5 attempts / 60s,
# see legacy/app/Http/Requests/Auth/LoginController/StoreRequest.php).
MAX_LOGIN_ATTEMPTS = 5
LOGIN_THROTTLE_WINDOW_SECONDS = 60

AuthFailureReason = Literal["unknown_email", "wrong_password", "account_locked"]


@overload
def _ensure_tz_aware(dt: datetime) -> datetime: ...
@overload
def _ensure_tz_aware(dt: None) -> None: ...
def _ensure_tz_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def log_auth_event(
    db: Session,
    event: str,
    email: str | None,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """1:1 port of Legacy's `AuthLog::log()` (app/Models/AuthLog.php) --
    write-only audit row, keyed by the raw submitted email string, not
    `user_id`. Commits immediately: the log must survive even if the
    caller's own transaction later fails."""
    db.add(
        AuthLog(
            event=event,
            fired_at=datetime.now(UTC),
            ip_address=ip_address,
            user_agent=user_agent,
            email=email,
            payload=payload or {},
        )
    )
    db.commit()


def check_login_throttle(db: Session, email: str, ip_address: str) -> int | None:
    """Returns seconds remaining if the email+IP pair is currently
    rate-limited, None if the login attempt may proceed.

    Mirrors Legacy's asymmetric Laravel RateLimiter semantics (hit on
    failure, cleared on success, key = lower(email)+ip) via a derived query
    over AuthLog instead of a separate counter/cache -- deliberately a
    sliding 60s window bounded by the most recent successful login for this
    exact key (an approximation of Laravel's fixed-window-with-clear-on-
    success cache semantics, not a bit-exact replication -- see the
    Schritt-2 plan for the full reasoning). No new table, reuses the audit
    trail as the source of truth (lean, DRY)."""
    now = datetime.now(UTC)
    window_start = now - timedelta(seconds=LOGIN_THROTTLE_WINDOW_SECONDS)
    normalized_email = email.lower()

    last_success_stmt = (
        select(AuthLog.fired_at)
        .where(
            AuthLog.event == "Login",
            func.lower(AuthLog.email) == normalized_email,
            AuthLog.ip_address == ip_address,
        )
        .order_by(AuthLog.fired_at.desc())
        .limit(1)
    )
    last_success = _ensure_tz_aware(db.execute(last_success_stmt).scalar_one_or_none())

    effective_start = window_start
    if last_success is not None and last_success > effective_start:
        effective_start = last_success

    failed_stmt = (
        select(AuthLog.fired_at)
        .where(
            AuthLog.event == "Failed",
            func.lower(AuthLog.email) == normalized_email,
            AuthLog.ip_address == ip_address,
            AuthLog.fired_at > effective_start,
        )
        .order_by(AuthLog.fired_at.asc())
    )
    raw_failed_times = db.execute(failed_stmt).scalars().all()
    failed_times = [_ensure_tz_aware(t) for t in raw_failed_times if t is not None]

    if len(failed_times) < MAX_LOGIN_ATTEMPTS:
        return None

    oldest_relevant = failed_times[-MAX_LOGIN_ATTEMPTS]
    retry_after = (
        oldest_relevant + timedelta(seconds=LOGIN_THROTTLE_WINDOW_SECONDS) - now
    )
    return max(1, int(retry_after.total_seconds()))


def authenticate_user(
    db: Session, email: str, password: str
) -> tuple[User | None, AuthFailureReason | Literal["ok"]]:
    """Case-sensitive email match, matching Legacy's actual DB comparison
    (SQLite default BINARY collation, no COLLATE NOCASE on `users.email`) --
    deliberately NOT lowercased here, unlike the throttle key above."""
    result = db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user is None:
        return None, "unknown_email"
    if not user.auth_password or not verify_password(password, user.auth_password):
        return None, "wrong_password"
    if user.auth_locked:
        return None, "account_locked"
    return user, "ok"


def create_user_session(db: Session, user: User) -> tuple[str, str, str]:
    if not user.email:
        msg = "User hat keine E-Mail-Adresse."
        raise ValueError(msg)

    access_token, session_id = create_access_token(subject=user.email)
    refresh_secret = generate_refresh_secret()
    now = datetime.now(UTC)

    db.add(
        PersonalAccessToken(
            user_id=user.id,
            name="session",
            token=session_id,
            refresh_token_hash=hash_refresh_secret(refresh_secret),
            last_used_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    user.auth_lastlogin = now
    db.commit()

    return access_token, session_id, refresh_secret


class InvalidSessionError(Exception):
    """Refresh token is missing, reused, or the underlying session/account
    is no longer valid -- the router maps this to a 401 + cookie clear."""


def _invalidate_session(
    db: Session, session: PersonalAccessToken, reason: str
) -> NoReturn:
    db.delete(session)
    db.commit()
    raise InvalidSessionError(reason)


def refresh_session(
    db: Session, session_id: str, refresh_secret: str
) -> tuple[str, str]:
    result = db.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        msg = "Invalid session"
        raise InvalidSessionError(msg)

    if not session.refresh_token_hash or not verify_refresh_secret(
        refresh_secret, session.refresh_token_hash
    ):
        _invalidate_session(db, session, "Token reuse detected")

    now = datetime.now(UTC)
    last_used = _ensure_tz_aware(session.last_used_at)
    if last_used and (now - last_used) > timedelta(
        minutes=SESSION_IDLE_TIMEOUT_MINUTES
    ):
        _invalidate_session(db, session, "Session expired due to inactivity")
    created = _ensure_tz_aware(session.created_at)
    if created and (now - created) > timedelta(days=REFRESH_TOKEN_LIFETIME_DAYS):
        _invalidate_session(db, session, "Session expired")

    user_result = db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or user.auth_locked or user.deleted_at is not None:
        _invalidate_session(db, session, "Account locked or deleted")
    if not user.email:
        _invalidate_session(db, session, "Account has no email")

    new_secret = generate_refresh_secret()
    session.refresh_token_hash = hash_refresh_secret(new_secret)
    session.last_used_at = now
    user.auth_lastsignal = now

    access_token, _ = create_access_token(subject=user.email, jti_override=session_id)
    db.commit()

    return access_token, new_secret


def logout_user(db: Session, token: str) -> None:
    try:
        payload = jwt.decode(
            token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False}
        )
    except jwt.PyJWTError:
        return

    token_id = payload.get("jti")
    if not token_id:
        return

    result = db.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token == token_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        return

    db.execute(
        update(User)
        .where(User.id == session.user_id)
        .values(auth_lastlogout=datetime.now(UTC))
    )
    db.delete(session)
    db.commit()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class RegistrationConflictError(Exception):
    """Field-level conflicts (email or name-combo already taken), surfaced
    to the router as a 422 in the same {"detail": [...]} shape FastAPI's
    own validation errors use."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        super().__init__("Registration conflict")


def check_registration_conflicts(
    db: Session, *, surname: str, givenname: str, email: str
) -> None:
    """Case-insensitive duplicate check, including soft-deleted users
    (User.deleted_at is deliberately NOT filtered out -- mirrors Legacy's
    `User::withTrashed()` check), so a deleted user's name/email can't be
    silently reused for a new registration."""
    errors: list[tuple[str, str]] = []

    name_taken = db.execute(
        select(User.id).where(
            func.lower(User.surname) == surname.lower(),
            func.lower(User.givenname) == givenname.lower(),
        )
    ).first()
    if name_taken is not None:
        msg = "Die Kombination von Vor- und Nachname ist vergeben."
        errors.append(("givenname", msg))
        errors.append(("surname", msg))

    email_taken = db.execute(
        select(User.id).where(func.lower(User.email) == email.lower())
    ).first()
    if email_taken is not None:
        msg = "Die E-Mail-Adresse wird bereits für ein bestehendes Konto verwendet."
        errors.append(("email", msg))

    if errors:
        raise RegistrationConflictError(errors)


def register_user(db: Session, data: RegisterRequest) -> User:
    """Persists the new User row. Auto-login (mirrors Legacy's
    `Auth::login($user)` right after `User::create()`) is the router's
    job via create_user_session(), not this function's."""
    check_registration_conflicts(
        db, surname=data.surname, givenname=data.givenname, email=data.email
    )

    user = User(
        surname=normalize_surname(data.surname),
        givenname=normalize_givenname(data.givenname),
        email=data.email.lower(),
        phone=data.phone,
        auth_password=get_password_hash(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------


def build_email_verification_token(user: User) -> str:
    if not user.email:
        msg = "User hat keine E-Mail-Adresse."
        raise ValueError(msg)
    return create_email_verification_token(user.id, user.email)


def verify_email(db: Session, token: str) -> User:
    settings = get_settings()
    invalid_msg = "Der Bestätigungslink ist ungültig oder abgelaufen."
    try:
        user_id, email_hash = decode_email_verification_token(
            token, max_age_seconds=settings.email_verification_ttl_minutes * 60
        )
    except InvalidVerificationTokenError:
        raise ValueError(invalid_msg) from None

    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None or not user.email:
        raise ValueError(invalid_msg)
    if hash_email_for_verification(user.email) != email_hash:
        # Email changed since the link was issued -- mirrors Legacy's
        # EmailVerificationRequest::authorize() sha1(email) re-check.
        raise ValueError(invalid_msg)

    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
        db.commit()
    return user


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


def request_password_reset(db: Session, email: str) -> str | None:
    """Returns the plain reset token if a matching user exists, None
    otherwise -- the router always responds 200 either way (no email
    enumeration), only queuing the actual mail when a token comes back."""
    normalized_email = email.lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == normalized_email)
    ).scalar_one_or_none()
    if user is None:
        return None

    db.execute(
        delete(PasswordResetToken).where(PasswordResetToken.email == normalized_email)
    )

    token = generate_reset_token()
    db.add(
        PasswordResetToken(
            email=normalized_email,
            token=hash_reset_token(token),
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    return token


def execute_password_reset(
    db: Session, email: str, token: str, new_password: str
) -> None:
    settings = get_settings()
    normalized_email = email.lower()
    # User-facing error text, not a credential.
    invalid_token_msg = "Der angegebene Token zur Passwort-Rücksetzung ist ungültig."  # noqa: S105

    reset_row = db.execute(
        select(PasswordResetToken).where(PasswordResetToken.email == normalized_email)
    ).scalar_one_or_none()
    if reset_row is None or not verify_reset_token(token, reset_row.token):
        raise ValueError(invalid_token_msg)

    created_at = _ensure_tz_aware(reset_row.created_at) or datetime.now(UTC)
    if datetime.now(UTC) - created_at > timedelta(
        minutes=settings.password_reset_ttl_minutes
    ):
        db.delete(reset_row)
        db.commit()
        raise ValueError(invalid_token_msg)

    user = db.execute(
        select(User).where(func.lower(User.email) == normalized_email)
    ).scalar_one_or_none()
    if user is None:
        msg = (
            "Ein Benutzerkonto mit dieser E-Mail-Adresse konnte nicht gefunden werden."
        )
        raise ValueError(msg)

    user.auth_password = get_password_hash(new_password)
    # Mirrors Legacy: a successful reset also verifies the email address.
    user.email_verified_at = datetime.now(UTC)

    db.execute(
        delete(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
    )
    db.delete(reset_row)
    db.commit()


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------


class AccountNotLinkedError(Exception):
    """Google token is valid, but not yet linked to any local account."""


class OauthBindingNotFoundError(Exception):
    """Binding doesn't exist, or doesn't belong to the requesting user --
    the router maps both cases to an identical 404 (no ID enumeration)."""


def _verify_google_id_token(credential: str) -> dict[str, Any]:
    settings = get_settings()
    client_id = require_setting(settings.google_client_id, "GOOGLE_CLIENT_ID")
    try:
        return dict(
            google_id_token.verify_oauth2_token(
                credential, google_requests.Request(), client_id
            )
        )
    except ValueError:
        msg = "Ungültiger oder abgelaufener Google-Token."
        raise ValueError(msg) from None


def authenticate_google_user(db: Session, credential: str) -> User:
    id_info = _verify_google_id_token(credential)
    google_id = id_info["sub"]

    binding = db.execute(
        select(Oauth2Binding).where(
            Oauth2Binding.provider == "google", Oauth2Binding.remote_id == google_id
        )
    ).scalar_one_or_none()
    if binding is None:
        raise AccountNotLinkedError

    user = db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == binding.local_id, User.deleted_at.is_(None))
    ).scalar_one_or_none()
    if user is None or user.auth_locked:
        msg = "Benutzerkonto gesperrt."
        raise ValueError(msg)

    binding.lastuse_at = datetime.now(UTC)
    user.auth_lastlogin_provider = "google"
    db.commit()
    return user


def link_google_account(
    db: Session, credential: str, email: str, password: str
) -> User:
    user, _reason = authenticate_user(db, email, password)
    if user is None:
        msg = "Anmeldedaten unbekannt."
        raise ValueError(msg)

    id_info = _verify_google_id_token(credential)
    google_id = id_info["sub"]
    google_name = id_info.get("name", "")

    existing = db.execute(
        select(Oauth2Binding).where(
            Oauth2Binding.provider == "google",
            (Oauth2Binding.remote_id == google_id)
            | (Oauth2Binding.local_id == user.id),
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is not None:
        if existing.local_id == user.id and existing.remote_id == google_id:
            existing.lastuse_at = now
            db.commit()
            return user
        msg = "Dieser Account oder dieses Google-Konto ist bereits verknüpft."
        raise ValueError(msg)

    db.add(
        Oauth2Binding(
            provider="google",
            remote_id=google_id,
            remote_name=google_name,
            local_id=user.id,
            bound_at=now,
            lastuse_at=now,
        )
    )
    db.commit()
    return user


def unlink_oauth_binding(db: Session, binding_id: int, current_user_id: int) -> None:
    """IDOR-fixed replacement for Legacy's `oauth2disconnect($id)` (which
    looked up `Oauth2Binding::find($id)` with NO ownership check -- any
    logged-in user could delete anyone else's Google link by iterating
    IDs). The lookup now filters on local_id too; not-found and
    not-owned both raise the same error -> one uniform 404, no
    enumeration signal."""
    binding = db.execute(
        select(Oauth2Binding).where(
            Oauth2Binding.id == binding_id, Oauth2Binding.local_id == current_user_id
        )
    ).scalar_one_or_none()
    if binding is None:
        raise OauthBindingNotFoundError

    db.delete(binding)
    db.commit()
