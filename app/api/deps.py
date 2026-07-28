from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import ALGORITHM, SECRET_KEY, SESSION_IDLE_TIMEOUT_MINUTES
from app.db.database import get_db
from app.db.models.personal_access_token import PersonalAccessToken
from app.db.models.user import User

# Tells FastAPI (and the Swagger UI) where a client can obtain a token.
# Caddy's `handle_path /api/*` already strips "/api" before this container
# ever sees the request (see main.py's root_path comment) -- the externally
# visible URL is "/api/auth/login", but the in-process route is "/auth/login".
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Anmeldedaten ungültig.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _decode_token(token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str | None = payload.get("sub")
        token_id: str | None = payload.get("jti")
        if email is None or token_id is None:
            raise _CREDENTIALS_EXCEPTION
    except jwt.PyJWTError:
        raise _CREDENTIALS_EXCEPTION from None
    else:
        return email, token_id


async def _get_session_record(db: AsyncSession, token_id: str) -> PersonalAccessToken:
    result = await db.execute(
        select(PersonalAccessToken).where(PersonalAccessToken.token == token_id)
    )
    session_record = result.scalar_one_or_none()
    if session_record is None:
        raise _CREDENTIALS_EXCEPTION
    return session_record


def _ensure_tz_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


async def _bump_lastsignal(db: AsyncSession, user_id: int, now: datetime) -> None:
    await db.execute(update(User).where(User.id == user_id).values(auth_lastsignal=now))


async def _enforce_idle_timeout(
    db: AsyncSession, session_record: PersonalAccessToken
) -> None:
    now = datetime.now(UTC)
    last_used = session_record.last_used_at

    if not last_used:
        session_record.last_used_at = now
        await _bump_lastsignal(db, session_record.user_id, now)
        await db.commit()
        return

    last_used = _ensure_tz_aware(last_used)
    idle_duration = now - last_used

    if idle_duration > timedelta(minutes=SESSION_IDLE_TIMEOUT_MINUTES):
        await db.delete(session_record)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session wegen Inaktivität abgelaufen.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if idle_duration > timedelta(minutes=1):
        session_record.last_used_at = now
        await _bump_lastsignal(db, session_record.user_id, now)
        await db.commit()


async def _get_verified_user(db: AsyncSession, email: str) -> User:
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise _CREDENTIALS_EXCEPTION
    if user.auth_locked:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Benutzerkonto gesperrt."
        )
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency that decodes+verifies the JWT, checks the revocable
    server-side session, enforces the idle timeout, and returns the User --
    with `roles` already eager-loaded so permission_service.calculate_permissions
    never triggers a lazy-load (no N+1 per authenticated request)."""
    email, token_id = _decode_token(token)
    session_record = await _get_session_record(db, token_id)
    await _enforce_idle_timeout(db, session_record)
    return await _get_verified_user(db, email)
