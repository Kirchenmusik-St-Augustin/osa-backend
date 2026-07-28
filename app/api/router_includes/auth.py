from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, oauth2_scheme
from app.core.rate_limit import limiter
from app.core.security import (
    REFRESH_TOKEN_LIFETIME_DAYS,
    build_refresh_cookie_value,
    parse_refresh_cookie,
)
from app.db.database import get_db
from app.db.models.user import User
from app.services import auth_service
from app.services.auth_service import InvalidSessionError

auth_router = APIRouter()

# Cookie path is the EXTERNAL (browser-visible) URL, not the in-process
# route -- Caddy strips "/api" before this container ever sees the request
# (see main.py's root_path comment), but the browser still stores/sends the
# cookie against "/api/auth/*" since that's the URL it actually requested.
COOKIE_PATH = "/api/auth"
COOKIE_MAX_AGE = REFRESH_TOKEN_LIFETIME_DAYS * 86400


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _build_login_response(
    access_token: str, session_id: str, refresh_secret: str
) -> JSONResponse:
    response = JSONResponse(
        content={"access_token": access_token, "token_type": "bearer"}
    )
    response.set_cookie(
        key="refresh_token",
        value=build_refresh_cookie_value(session_id, refresh_secret),
        httponly=True,
        secure=True,
        samesite="lax",
        path=COOKIE_PATH,
        max_age=COOKIE_MAX_AGE,
    )
    return response


@auth_router.post("/login")
def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    """Authenticate with email + password, receive a JWT access token plus
    an httponly refresh cookie.

    Exact German error texts are hard Legacy parity (lang/de/auth.php):
    "Anmeldedaten unbekannt." covers BOTH unknown email and wrong password
    (Laravel's Auth::attempt() fails generically for both -- there is no
    separate "Passwort falsch." message in the login flow, that string
    belongs to the unrelated self-service change-password form). Lockout
    threshold/window (5 attempts / 60s) also hard parity, see
    auth_service.check_login_throttle.
    """
    ip_address = _client_ip(request)
    user_agent = request.headers.get("user-agent")

    seconds_remaining = auth_service.check_login_throttle(
        db, form_data.username, ip_address
    )
    if seconds_remaining is not None:
        auth_service.log_auth_event(
            db,
            "Lockout",
            form_data.username,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        minutes = ceil(seconds_remaining / 60)
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": (
                    f"Zu viele Anmeldeversuche. Bitte in {seconds_remaining} "
                    "Sekunden erneut versuchen."
                ),
                "seconds": seconds_remaining,
                "minutes": minutes,
            },
        )

    user, reason = auth_service.authenticate_user(
        db, form_data.username, form_data.password
    )

    if reason == "account_locked":
        auth_service.log_auth_event(
            db,
            "Failed",
            form_data.username,
            ip_address=ip_address,
            user_agent=user_agent,
            payload={"reason": "account_locked"},
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "Benutzerkonto gesperrt."},
        )

    if user is None:
        auth_service.log_auth_event(
            db,
            "Failed",
            form_data.username,
            ip_address=ip_address,
            user_agent=user_agent,
            payload={"valid_auth_name": reason != "unknown_email"},
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Anmeldedaten unbekannt."},
        )

    access_token, session_id, refresh_secret = auth_service.create_user_session(
        db, user
    )
    auth_service.log_auth_event(
        db, "Login", user.email, ip_address=ip_address, user_agent=user_agent
    )

    return _build_login_response(access_token, session_id, refresh_secret)


@auth_router.post("/refresh")
@limiter.limit("10/minute")  # type: ignore[reportUntypedFunctionDecorator]
def refresh(request: Request, db: Annotated[Session, Depends(get_db)]) -> JSONResponse:
    """Exchange the refresh-token cookie for a new access token, rotating
    the refresh secret on every use. No Legacy equivalent (Legacy has no
    JWT refresh concept at all) -- per-IP rate limit only, 1:1 vb-api."""
    cookie_value = request.cookies.get("refresh_token")
    if not cookie_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kein Refresh-Token vorhanden.",
        )

    try:
        session_id, refresh_secret = parse_refresh_cookie(cookie_value)
        access_token, new_secret = auth_service.refresh_session(
            db, session_id, refresh_secret
        )
    except (ValueError, InvalidSessionError):
        response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Session abgelaufen oder ungültig."},
        )
        response.delete_cookie("refresh_token", path=COOKIE_PATH)
        return response

    return _build_login_response(access_token, session_id, new_secret)


@auth_router.post("/logout")
def logout(
    _request: Request,
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JSONResponse:
    """Invalidate the current session and clear the refresh-token cookie."""
    auth_service.logout_user(db, token)
    auth_service.log_auth_event(db, "Logout", current_user.email)
    response = JSONResponse(
        content={"status": "ok", "message": "Erfolgreich abgemeldet."}
    )
    response.delete_cookie("refresh_token", path=COOKIE_PATH)
    return response
