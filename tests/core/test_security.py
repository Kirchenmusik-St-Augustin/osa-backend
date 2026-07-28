from datetime import timedelta

import jwt
import pytest

from app.core import security


def test_get_password_hash_and_verify_roundtrip():
    hashed = security.get_password_hash("hunter2")

    assert security.verify_password("hunter2", hashed)
    assert not security.verify_password("wrong", hashed)


def test_verify_password_normalizes_legacy_2y_prefix():
    """Legacy passwords are real PHP `password_hash()` output ($2y$ prefix)
    -- Python's bcrypt only accepts $2a$/$2b$, so verify_password must
    normalize the prefix before checking, or every migrated user's password
    would break on first login."""
    php_style_hash = security.get_password_hash("hunter2").replace("$2b$", "$2y$", 1)

    assert security.verify_password("hunter2", php_style_hash)


def test_verify_password_rejects_none_or_empty_hash():
    assert not security.verify_password("hunter2", None)
    assert not security.verify_password("hunter2", "")


def test_verify_password_handles_malformed_hash_gracefully():
    assert not security.verify_password("hunter2", "not-a-real-bcrypt-hash")


def test_create_access_token_roundtrip():
    token, jti = security.create_access_token(subject="user@example.test")

    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload["sub"] == "user@example.test"
    assert payload["jti"] == jti


def test_create_access_token_respects_jti_override():
    _token, jti = security.create_access_token(
        subject="user@example.test", jti_override="fixed-session-id"
    )

    assert jti == "fixed-session-id"


def test_create_access_token_respects_custom_expiry():
    token, _jti = security.create_access_token(
        subject="user@example.test", expires_delta=timedelta(minutes=1)
    )

    payload = jwt.decode(token, security.SECRET_KEY, algorithms=[security.ALGORITHM])
    assert payload["exp"] - payload["iat"] == 60


def test_generate_and_hash_refresh_secret_roundtrip():
    secret = security.generate_refresh_secret()
    hashed = security.hash_refresh_secret(secret)

    assert security.verify_refresh_secret(secret, hashed)
    assert not security.verify_refresh_secret("wrong-secret", hashed)


def test_build_and_parse_refresh_cookie_roundtrip():
    cookie_value = security.build_refresh_cookie_value("session-id", "refresh-secret")

    session_id, refresh_secret = security.parse_refresh_cookie(cookie_value)

    assert session_id == "session-id"
    assert refresh_secret == "refresh-secret"


def test_parse_refresh_cookie_rejects_malformed_value():
    with pytest.raises(ValueError, match="Malformed refresh cookie"):
        security.parse_refresh_cookie("no-colon-here")

    with pytest.raises(ValueError, match="Malformed refresh cookie"):
        security.parse_refresh_cookie("only-one:")

    with pytest.raises(ValueError, match="Malformed refresh cookie"):
        security.parse_refresh_cookie(":only-two")


def test_email_verification_token_roundtrip():
    token = security.create_email_verification_token(42, "user@example.test")

    user_id, email_hash = security.decode_email_verification_token(
        token, max_age_seconds=3600
    )

    assert user_id == 42
    assert email_hash == security.hash_email_for_verification("user@example.test")


def test_email_verification_token_rejects_expired_token():
    token = security.create_email_verification_token(42, "user@example.test")

    with pytest.raises(security.InvalidVerificationTokenError):
        security.decode_email_verification_token(token, max_age_seconds=-1)


def test_email_verification_token_rejects_tampered_token():
    token = security.create_email_verification_token(42, "user@example.test")

    with pytest.raises(security.InvalidVerificationTokenError):
        security.decode_email_verification_token(
            token + "tampered", max_age_seconds=3600
        )


def test_hash_email_for_verification_is_case_sensitive_and_deterministic():
    first = security.hash_email_for_verification("user@example.test")
    second = security.hash_email_for_verification("user@example.test")
    different = security.hash_email_for_verification("USER@example.test")

    assert first == second
    assert first != different


def test_generate_and_hash_reset_token_roundtrip():
    token = security.generate_reset_token()
    hashed = security.hash_reset_token(token)

    assert security.verify_reset_token(token, hashed)
    assert not security.verify_reset_token("wrong-token", hashed)
