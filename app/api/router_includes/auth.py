from math import ceil
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.auth_guards import get_verified_user
from app.api.deps import get_current_user, oauth2_scheme
from app.api.error_responses import field_errors_to_detail
from app.core import mailer
from app.core.config import get_settings, require_setting
from app.core.rate_limit import limiter
from app.core.security import (
    REFRESH_TOKEN_LIFETIME_DAYS,
    build_refresh_cookie_value,
    parse_refresh_cookie,
)
from app.db.database import get_db
from app.db.models.user import User
from app.schemas.auth import (
    EmailKillSwitchStatusOutput,
    ForgotPasswordRequest,
    GoogleCallbackRequest,
    GoogleLinkRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserProfileResponse,
    VerifyEmailRequest,
)
from app.services import auth_service
from app.services.auth_service import (
    AccountNotLinkedError,
    InvalidSessionError,
    OauthBindingNotFoundError,
    RegistrationConflictError,
)
from app.services.permission_service import calculate_permissions

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
        samesite="none",
        path=COOKIE_PATH,
        max_age=COOKIE_MAX_AGE,
    )
    return response


def _ensure_trusted_origin(request: Request) -> None:
    """CSRF defense for /refresh: samesite="none" on the refresh-token
    cookie above (required so a future frontend/backend domain split keeps
    working) means the browser now attaches that cookie to a cross-site
    request too, not just requests from our own frontend. /refresh is the
    one endpoint that acts purely on that cookie, no Authorization header
    required (unlike /logout, see get_current_user), so it's the one
    actually exposed to that. A browser always sends an Origin header on a
    POST, so a missing/untrusted one means this request didn't originate
    from a page we serve."""
    origin = request.headers.get("origin")
    if origin not in get_settings().cors_origins_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anfrage-Herkunft nicht vertrauenswürdig.",
        )


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
    _ensure_trusted_origin(request)
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


@auth_router.get("/me")
def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserProfileResponse:
    """No Legacy route equivalent -- Legacy's Inertia setup injects the
    user into every server-rendered page's shared props, a pure SPA has
    no such channel. The frontend calls this once after login/on boot to
    populate its auth store (navbar display, permission-gated UI,
    Schritt 7's email-kill-switch warning icon -- same lifecycle as
    `permissions`, no separate polling endpoint)."""
    kill_switch = mailer.get_kill_switch_status(db)
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email or "",
        email_verified_at=current_user.email_verified_at,
        surname=current_user.surname,
        givenname=current_user.givenname,
        administrator=current_user.administrator,
        permissions=calculate_permissions(current_user),
        email_kill_switch=EmailKillSwitchStatusOutput(
            active=kill_switch.active,
            period_days=kill_switch.period_days,
            threshold=kill_switch.threshold,
        ),
    )


@auth_router.post("/register")
def register(
    data: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    """Register + auto-login (mirrors Legacy's `Auth::login($user)` right
    after `User::create()`), then notify the disponent address in the
    background -- registration itself must not wait on (or fail because
    of) mail delivery."""
    try:
        user = auth_service.register_user(db, data)
    except RegistrationConflictError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": field_errors_to_detail(exc.errors)},
        )

    background_tasks.add_task(
        mailer.send_new_registration_notice,
        surname=user.surname,
        givenname=user.givenname,
        email=data.email.lower(),
        phone=user.phone,
    )
    if user.email is not None:
        verify_url = auth_service.build_verification_email_url(user)
        background_tasks.add_task(
            mailer.send_verification_email, user.email, verify_url
        )

    access_token, session_id, refresh_secret = auth_service.create_user_session(
        db, user
    )
    return _build_login_response(access_token, session_id, refresh_secret)


@auth_router.post("/resend-verification-email")
@limiter.limit("6/minute")  # type: ignore[reportUntypedFunctionDecorator]
def resend_verification_email(
    request: Request,  # noqa: ARG001 -- slowapi's @limiter.limit requires a literal "request" param, even though the body never reads it
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """1:1 Legacy's `POST verify-email` (EmailVerificationController::send()).
    Deliberately uses get_current_user, not get_verified_user -- an
    unverified user must be able to reach exactly this endpoint. No-op
    (still 200) if already verified, matching Legacy's own idempotent
    `hasVerifiedEmail()` short-circuit."""
    if current_user.email_verified_at is None and current_user.email is not None:
        verify_url = auth_service.build_verification_email_url(current_user)
        background_tasks.add_task(
            mailer.send_verification_email, current_user.email, verify_url
        )
    return {
        "status": "ok",
        "message": "Die Überprüfungs-E-Mail wurde erneut versandt.",
    }


@auth_router.post("/verify-email")
def verify_email(
    data: VerifyEmailRequest, db: Annotated[Session, Depends(get_db)]
) -> JSONResponse:
    """Self-contained via the token alone (no prior login required) --
    the token already encodes+signs the target user, playing the same
    role Legacy's Laravel Signed Route + auth-middleware combination did.
    Auto-logs the user in afterwards, since Legacy's equivalent flow
    always already had an active session at this point."""
    try:
        user = auth_service.verify_email(db, data.token)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    auth_service.log_auth_event(db, "Verified", user.email)

    access_token, session_id, refresh_secret = auth_service.create_user_session(
        db, user
    )
    return _build_login_response(access_token, session_id, refresh_secret)


@auth_router.post("/forgot-password")
def forgot_password(
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """Always responds 200 regardless of whether the email is registered
    -- prevents account enumeration (1:1 Legacy UX, even though Legacy's
    own server-side validation actually leaks this via a distinct
    "passwords.user" error; the neutral-response behavior is the
    hardening, not a Legacy replication)."""
    token = auth_service.request_password_reset(db, data.email)
    if token is not None:
        settings = get_settings()
        base_url = require_setting(
            settings.frontend_reset_password_url, "FRONTEND_RESET_PASSWORD_URL"
        )
        reset_url = f"{base_url}?{urlencode({'token': token, 'email': data.email})}"
        background_tasks.add_task(
            mailer.send_password_reset_email, data.email, reset_url
        )
    return {
        "status": "ok",
        "message": (
            "Falls die E-Mail-Adresse registriert ist, wurde ein Reset-Link versendet."
        ),
    }


@auth_router.post("/reset-password")
def reset_password(
    data: ResetPasswordRequest, db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    try:
        auth_service.execute_password_reset(db, data.email, data.token, data.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    auth_service.log_auth_event(db, "PasswordReset", data.email)
    return {"status": "ok", "message": "Das Passwort wurde zurückgesetzt."}


@auth_router.post("/google/callback")
def google_callback(
    data: GoogleCallbackRequest, db: Annotated[Session, Depends(get_db)]
) -> JSONResponse:
    """Direct login via an existing Google binding. No Legacy-equivalent
    redirect/callback dance (Socialite's server-side OAuth code exchange
    needs session-stored CSRF `state`, which doesn't cleanly exist in a
    stateless-JWT backend) -- uses Google Identity Services' ID-token
    ("credential") flow instead, 1:1 the simpler pattern already proven
    for this exact use case. Same business capability (log in if already
    linked), leaner mechanism."""
    try:
        user = auth_service.authenticate_google_user(db, data.credential)
    except AccountNotLinkedError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "ACCOUNT_NOT_LINKED"},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from None

    access_token, session_id, refresh_secret = auth_service.create_user_session(
        db, user
    )
    return _build_login_response(access_token, session_id, refresh_secret)


@auth_router.post("/google/link")
def google_link(
    data: GoogleLinkRequest, db: Annotated[Session, Depends(get_db)]
) -> JSONResponse:
    try:
        user = auth_service.link_google_account(
            db, data.credential, data.email, data.password
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from None

    access_token, session_id, refresh_secret = auth_service.create_user_session(
        db, user
    )
    return _build_login_response(access_token, session_id, refresh_secret)


@auth_router.delete("/oauth2/{binding_id}")
def disconnect_oauth2_binding(
    binding_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_verified_user)],
) -> dict[str, str]:
    """IDOR-fixed replacement for Legacy's `oauth2disconnect($id)` -- see
    auth_service.unlink_oauth_binding for the vulnerability this closes.
    """
    try:
        auth_service.unlink_oauth_binding(db, binding_id, current_user.id)
    except OauthBindingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nicht gefunden."
        ) from None
    return {"status": "ok", "message": "Google-Verknüpfung wurde erfolgreich gelöst."}
