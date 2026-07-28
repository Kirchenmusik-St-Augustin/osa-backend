import hashlib
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import bcrypt
import jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()

# Settings._validate_tier1 already exits the process if secret_key is unset,
# so by the time get_settings() returns, it is guaranteed non-None.
SECRET_KEY = cast("str", _settings.secret_key)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = _settings.session_lifetime_minutes
SESSION_IDLE_TIMEOUT_MINUTES = _settings.session_idle_timeout_minutes
REFRESH_TOKEN_LIFETIME_DAYS = _settings.refresh_token_lifetime_days


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Legacy passwords are real bcrypt hashes in PHP's `$2y$` form
    (`password_hash()`'s default prefix) -- Python's bcrypt only accepts
    `$2a$`/`$2b$`. Both prefixes denote the exact same algorithm revision
    for any password that doesn't hit the historical 8-bit-vs-7-bit-high-bit
    edge case, so normalizing the prefix before verifying is safe and lets
    every already-migrated Legacy user log in unchanged (1:1 vb-api
    pattern)."""
    try:
        if not hashed_password:
            return False
        if hashed_password.startswith("$2y$"):
            hashed_password = hashed_password.replace("$2y$", "$2b$", 1)
        password_bytes = plain_password.encode("utf-8")
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except ValueError:
        logger.exception("Bcrypt verification error")
        return False


def get_password_hash(password: str) -> str:
    password_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    jti_override: str | None = None,
) -> tuple[str, str]:
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    token_id = jti_override or str(uuid.uuid4())
    to_encode = {
        "exp": expire,
        "iat": datetime.now(UTC),
        "sub": str(subject),
        "jti": token_id,
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt, token_id


def generate_refresh_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def verify_refresh_secret(plain: str, hashed: str) -> bool:
    return hashlib.sha256(plain.encode()).hexdigest() == hashed


def build_refresh_cookie_value(session_id: str, refresh_secret: str) -> str:
    return f"{session_id}:{refresh_secret}"


def parse_refresh_cookie(cookie_value: str) -> tuple[str, str]:
    parts = cookie_value.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        msg = "Malformed refresh cookie"
        raise ValueError(msg)
    return parts[0], parts[1]


_EMAIL_VERIFICATION_SALT = "email-verification"
_email_verification_serializer = URLSafeTimedSerializer(
    SECRET_KEY, salt=_EMAIL_VERIFICATION_SALT
)


class InvalidVerificationTokenError(Exception):
    """Token is malformed, expired, or was tampered with."""


def create_email_verification_token(user_id: int, email: str) -> str:
    """Mirrors Legacy's Laravel Signed URL for email verification 1:1
    (Illuminate\\Auth\\Notifications\\VerifyEmail): payload is
    {user_id, sha1(email)}. sha1 here is only a cheap "has the email
    changed since" fingerprint, not a security boundary -- tamper
    protection comes from itsdangerous' HMAC signature around the whole
    payload, not from sha1's collision resistance."""
    email_hash = hashlib.sha1(email.encode(), usedforsecurity=False).hexdigest()
    return _email_verification_serializer.dumps(
        {"user_id": user_id, "email_hash": email_hash}
    )


def decode_email_verification_token(
    token: str, max_age_seconds: int
) -> tuple[int, str]:
    try:
        payload = _email_verification_serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        raise InvalidVerificationTokenError from None
    return payload["user_id"], payload["email_hash"]


def hash_email_for_verification(email: str) -> str:
    return hashlib.sha1(email.encode(), usedforsecurity=False).hexdigest()


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    # Deliberate hardening over a plaintext-stored reset token: a random
    # secret sitting in the DB in the clear is an avoidable risk (DB
    # backup leak, overly-broad admin access) for a two-line fix -- same
    # hash-before-persist pattern already used for refresh secrets above.
    return hashlib.sha256(token.encode()).hexdigest()


def verify_reset_token(plain: str, hashed: str) -> bool:
    return hashlib.sha256(plain.encode()).hexdigest() == hashed
