from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NoReturn, overload

import jwt
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.security import (
    ALGORITHM,
    REFRESH_TOKEN_LIFETIME_DAYS,
    SECRET_KEY,
    SESSION_IDLE_TIMEOUT_MINUTES,
    create_access_token,
    generate_refresh_secret,
    hash_refresh_secret,
    verify_password,
    verify_refresh_secret,
)
from app.db.models.auth_log import AuthLog
from app.db.models.personal_access_token import PersonalAccessToken
from app.db.models.user import User

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
