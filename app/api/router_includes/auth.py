import uuid
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.auth_guards import AuthUser, get_verified_user
from app.api.deps import get_current_user, oauth2_scheme
from app.api.job_queue import JobQueue, get_job_queue
from app.core import mailer
from app.core.config import get_settings
from app.core.rate_limit import client_ip, rate_limited
from app.core.redacted import Redacted
from app.core.security import (
    REFRESH_TOKEN_LIFETIME_DAYS,
    build_refresh_cookie_value,
    parse_refresh_cookie,
)
from app.db.database import get_db
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
    RegistrationConflict,
)
from app.services.permission_service import calculate_permissions
from app.worker.tasks import (
    send_new_registration_notice_task,
    send_password_reset_email_task,
    send_registration_account_exists_email_task,
    send_registration_entry_exists_email_task,
    send_verification_email_task,
)

auth_router = APIRouter()

# Cookie path is the EXTERNAL (browser-visible) URL, not the in-process
# route -- Caddy strips "/api" before this container ever sees the request
# (see main.py's root_path comment), but the browser still stores/sends the
# cookie against "/api/auth/*" since that's the URL it actually requested.
COOKIE_PATH = "/api/auth"
COOKIE_MAX_AGE = REFRESH_TOKEN_LIFETIME_DAYS * 86400


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
        samesite=get_settings().refresh_cookie_samesite,
        path=COOKIE_PATH,
        max_age=COOKIE_MAX_AGE,
    )
    return response


def _ensure_trusted_origin(request: Request) -> None:
    """CSRF defense for /refresh, second layer behind the SameSite attribute of
    the refresh-token cookie above. With REFRESH_COOKIE_SAMESITE=none (needed
    when the frontend and the API live on different registrable domains) the
    browser attaches the cookie to a cross-site request too, not just
    requests from our own frontend. /refresh is the one endpoint that acts
    purely on that cookie, no Authorization header required (unlike /logout,
    see get_current_user), so it's the one actually exposed to that. A
    browser always sends an Origin header on a POST, so a missing/untrusted
    one means this request didn't originate from a page we serve."""
    origin = request.headers.get("origin")
    if origin not in get_settings().cors_origins_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anfrage-Herkunft nicht vertrauenswürdig.",
        )


def _throttled_response(seconds_remaining: int) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": (
                f"Zu viele Anmeldeversuche. Bitte in {seconds_remaining} "
                "Sekunden erneut versuchen."
            ),
            "seconds": seconds_remaining,
            "minutes": ceil(seconds_remaining / 60),
        },
    )


@auth_router.post("/login")
def login(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    """Authenticate with email + password, receive a JWT access token plus
    an httponly refresh cookie.

    "Anmeldedaten unbekannt." covers BOTH unknown email and wrong password
    (the login fails generically for both, which prevents account
    enumeration -- there is no separate "Passwort falsch." message in the
    login flow, that string belongs to the unrelated self-service
    change-password form). Lockout: 5 failed attempts / 60s per e-mail and
    address, 20 / 15 min per e-mail from any address, see
    auth_service.check_login_throttle.
    """
    ip_address = client_ip(request)
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
        return _throttled_response(seconds_remaining)

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
@rate_limited("10/minute")
def refresh(request: Request, db: Annotated[Session, Depends(get_db)]) -> JSONResponse:
    """Exchange the refresh-token cookie for a new access token, rotating
    the refresh secret on every use. Per-IP rate limit only."""
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
    except ValueError, InvalidSessionError:
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
    current_user: Annotated[AuthUser, Depends(get_current_user)],
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
    current_user: Annotated[AuthUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> UserProfileResponse:
    """The frontend calls this once after login/on boot to populate its auth
    store (navbar display, permission-gated UI, email-kill-switch warning
    icon -- same lifecycle as `permissions`, no separate polling
    endpoint)."""
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


def _registration_notice(email: str) -> dict[str, str]:
    return {
        "status": "ok",
        "message": (
            f"Bitte prüfe dein Postfach. Wir haben eine E-Mail an {email} "
            "geschickt. Falls für diese Adresse noch kein Konto besteht, "
            "enthält sie einen Bestätigungslink. Nach der Bestätigung bist "
            "du angemeldet."
        ),
    }


@auth_router.post("/register")
@rate_limited("5/hour")
def register(
    request: Request,  # noqa: ARG001
    data: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> dict[str, str]:
    """Answers every registration alike, so an anonymous visitor cannot learn
    whether an address or a name is already in use (the login and reset flows
    avoid the same enumeration). A new address gets its account, the
    verification mail and, in the background, the disponent notice; no session
    is issued, the verification link logs in. An address that has an account,
    or a name that is taken, creates nothing and gets a mail saying so.
    Registration itself must not wait on (or fail because of) mail delivery.
    No auth/permission dependency exists on this endpoint (it must work
    logged-out), so there is no dependency-ordering concern here, unlike
    resend_verification_email below."""
    outcome = auth_service.register_user(db, data)
    email = data.email.lower()

    if outcome is RegistrationConflict.ACCOUNT_EXISTS:
        job_queue.enqueue(send_registration_account_exists_email_task, email)
        return _registration_notice(email)
    if outcome is RegistrationConflict.ENTRY_EXISTS:
        job_queue.enqueue(
            send_registration_entry_exists_email_task,
            email,
            data.givenname,
            data.surname,
        )
        return _registration_notice(email)

    user = outcome
    job_queue.enqueue(
        send_new_registration_notice_task,
        surname=user.surname,
        givenname=user.givenname,
        email=data.email.lower(),
        phone=user.phone,
    )
    if user.email is not None:
        verify_url = auth_service.build_verification_email_url(user)
        job_queue.enqueue(
            send_verification_email_task, user.email, Redacted(verify_url)
        )

    return _registration_notice(email)


@auth_router.post("/resend-verification-email")
@rate_limited("6/minute")
def resend_verification_email(
    request: Request,  # noqa: ARG001
    current_user: Annotated[AuthUser, Depends(get_current_user)],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> dict[str, str]:
    """Re-sends the verification mail. Deliberately uses get_current_user,
    not get_verified_user -- an unverified user must be able to reach
    exactly this endpoint. Idempotent: no-op (still 200) if already
    verified. current_user is declared BEFORE job_queue on purpose, see
    get_job_queue."""
    if current_user.email_verified_at is None and current_user.email is not None:
        verify_url = auth_service.build_verification_email_url(current_user)
        job_queue.enqueue(
            send_verification_email_task, current_user.email, Redacted(verify_url)
        )
    return {
        "status": "ok",
        "message": "Die Überprüfungs-E-Mail wurde erneut versandt.",
    }


@auth_router.post("/verify-email")
@rate_limited("5/hour")
def verify_email(
    request: Request,  # noqa: ARG001
    data: VerifyEmailRequest,
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    """Self-contained via the token alone (no prior login required) --
    the token already encodes+signs the target user. Auto-logs the user in
    afterwards, since the link is typically opened in a fresh browser
    context without an active session."""
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
@rate_limited("5/hour")
def forgot_password(
    request: Request,  # noqa: ARG001
    data: ForgotPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
    job_queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> dict[str, str]:
    """Always responds 200 regardless of whether the email is registered
    -- prevents account enumeration. No auth/permission dependency
    exists on this endpoint (must work logged-out), so unlike
    resend_verification_email above there is no dependency-ordering
    concern here -- db and job_queue are the only two dependencies and
    neither one rejects the request."""
    reset_url = auth_service.build_password_reset_url(db, data.email)
    if reset_url is not None:
        job_queue.enqueue(
            send_password_reset_email_task, data.email, Redacted(reset_url)
        )
    return {
        "status": "ok",
        "message": (
            "Falls die E-Mail-Adresse registriert ist, wurde ein Reset-Link versendet."
        ),
    }


@auth_router.post("/reset-password")
@rate_limited("5/hour")
def reset_password(
    request: Request,  # noqa: ARG001
    data: ResetPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
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
@rate_limited("5/hour")
def google_callback(
    request: Request,  # noqa: ARG001
    data: GoogleCallbackRequest,
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    """Direct login via an existing Google binding. Uses Google Identity
    Services' ID-token ("credential") flow rather than a server-side OAuth
    redirect/callback dance, which would need a session-stored CSRF `state`
    that doesn't cleanly exist in a stateless-JWT backend."""
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
@rate_limited("5/hour")
def google_link(
    request: Request,
    data: GoogleLinkRequest,
    db: Annotated[Session, Depends(get_db)],
) -> JSONResponse:
    """Checks the local e-mail and password, so it shares the login lockout
    and audit trail: otherwise it would be a way to guess passwords that
    the login throttle never sees."""
    ip_address = client_ip(request)
    user_agent = request.headers.get("user-agent")

    seconds_remaining = auth_service.check_login_throttle(db, data.email, ip_address)
    if seconds_remaining is not None:
        auth_service.log_auth_event(
            db,
            "Lockout",
            data.email,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return _throttled_response(seconds_remaining)

    try:
        user = auth_service.link_google_account(
            db, data.credential, data.email, data.password
        )
    except ValueError as exc:
        auth_service.log_auth_event(
            db,
            "Failed",
            data.email,
            ip_address=ip_address,
            user_agent=user_agent,
            payload={"via": "google_link"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from None

    access_token, session_id, refresh_secret = auth_service.create_user_session(
        db, user
    )
    auth_service.log_auth_event(
        db, "Login", user.email, ip_address=ip_address, user_agent=user_agent
    )
    return _build_login_response(access_token, session_id, refresh_secret)


@auth_router.delete("/oauth2/{binding_id}")
def disconnect_oauth2_binding(
    binding_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[AuthUser, Depends(get_verified_user)],
) -> dict[str, str]:
    """Unlinks an OAuth binding, restricted to the caller's own bindings --
    see auth_service.unlink_oauth_binding for the IDOR protection.
    """
    try:
        auth_service.unlink_oauth_binding(db, binding_id, current_user.id)
    except OauthBindingNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nicht gefunden."
        ) from None
    return {"status": "ok", "message": "Google-Verknüpfung wurde erfolgreich gelöst."}
