import uuid

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_valid_settings_parses_cors_origins_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    settings = Settings()

    assert settings.cors_origins_list == ["https://a.example", "https://b.example"]


def test_missing_app_environment_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    with pytest.raises(SystemExit):
        Settings()


def test_invalid_app_environment_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "not-a-real-environment")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    with pytest.raises(SystemExit):
        Settings()


def test_missing_cors_origins_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    with pytest.raises(SystemExit):
        Settings()


def test_blank_cors_origins_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", " , ")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")

    with pytest.raises(SystemExit):
        Settings()


def test_missing_database_url_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit):
        Settings()


def test_missing_secret_key_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(SystemExit):
        Settings()


def test_too_short_secret_key_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("SECRET_KEY", "too-short")

    with pytest.raises(SystemExit):
        Settings()


def test_placeholder_secret_key_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv(
        "SECRET_KEY", "changeme-generate-a-real-32-plus-character-secret"
    )

    with pytest.raises(SystemExit):
        Settings()

    assert "template placeholder" in capsys.readouterr().err


def test_placeholder_marker_is_detected_in_any_case_and_position(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("SECRET_KEY", "0123456789abcdef-ChangeMe-0123456789abcdef")

    with pytest.raises(SystemExit):
        Settings()

    assert "template placeholder" in capsys.readouterr().err


def test_empty_secret_key_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("SECRET_KEY", "")

    with pytest.raises(SystemExit):
        Settings()

    assert "SECRET_KEY is not set" in capsys.readouterr().err


def test_app_timezone_defaults_to_europe_vienna():
    assert Settings().app_timezone == "Europe/Vienna"


def test_app_timezone_can_be_overridden(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")

    assert Settings().app_timezone == "America/New_York"


def test_valid_secret_key_and_tier2_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.delenv("SESSION_LIFETIME_MINUTES", raising=False)
    monkeypatch.delenv("SESSION_IDLE_TIMEOUT_MINUTES", raising=False)
    monkeypatch.delenv("REFRESH_TOKEN_LIFETIME_DAYS", raising=False)

    settings = Settings()

    assert settings.secret_key is not None
    assert settings.secret_key.get_secret_value() == "x" * 32
    assert settings.session_lifetime_minutes == 15
    assert settings.session_idle_timeout_minutes == 120
    assert settings.refresh_token_lifetime_days == 7


def test_koofr_backup_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("KOOFR_BASE_URI", raising=False)
    monkeypatch.delenv("KOOFR_BACKUP_PATH", raising=False)
    monkeypatch.delenv("KOOFR_BACKUP_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("BACKUP_ENABLED", raising=False)
    monkeypatch.delenv("BACKUP_HOUR", raising=False)
    monkeypatch.delenv("BACKUP_MINUTE", raising=False)
    monkeypatch.delenv("KOOFR_USER", raising=False)
    monkeypatch.delenv("KOOFR_PASSWORD", raising=False)

    settings = Settings()

    assert settings.koofr_base_uri == "https://app.koofr.net/dav/"
    assert settings.koofr_backup_path == "Koofr/Backups/osa-db"
    assert settings.koofr_backup_retention_days == 28
    assert settings.backup_enabled is True
    assert settings.backup_hour == 3
    assert settings.backup_minute == 0
    assert settings.koofr_user is None
    assert settings.koofr_password is None


def test_koofr_backup_settings_can_be_overridden(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KOOFR_BASE_URI", "https://example.test/dav/")
    monkeypatch.setenv("KOOFR_BACKUP_PATH", "Backups/other-path")
    monkeypatch.setenv("KOOFR_BACKUP_RETENTION_DAYS", "14")
    monkeypatch.setenv("BACKUP_ENABLED", "false")
    monkeypatch.setenv("BACKUP_HOUR", "7")
    monkeypatch.setenv("BACKUP_MINUTE", "15")
    monkeypatch.setenv("KOOFR_USER", "someone")
    monkeypatch.setenv("KOOFR_PASSWORD", "secret")

    settings = Settings()

    assert settings.koofr_base_uri == "https://example.test/dav/"
    assert settings.koofr_backup_path == "Backups/other-path"
    assert settings.koofr_backup_retention_days == 14
    assert settings.backup_enabled is False
    assert settings.backup_hour == 7
    assert settings.backup_minute == 15
    assert settings.koofr_user == "someone"
    assert settings.koofr_password is not None
    assert settings.koofr_password.get_secret_value() == "secret"


def test_performance_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PERFORMANCE_DEFAULT_LOCATION_ID", raising=False)
    monkeypatch.delenv("PERFORMANCE_DEFAULT_CONDUCTOR_ARTIST_ID", raising=False)

    settings = Settings()

    # No built-in default makes sense for a UUID primary key (unlike the
    # other Tier 2 settings) -- absent configuration means no pre-fill.
    assert settings.performance_default_location_id is None
    assert settings.performance_default_conductor_artist_id is None


def test_performance_defaults_can_be_overridden(monkeypatch: pytest.MonkeyPatch):
    location_id = uuid.uuid4()
    conductor_id = uuid.uuid4()
    monkeypatch.setenv("PERFORMANCE_DEFAULT_LOCATION_ID", str(location_id))
    monkeypatch.setenv("PERFORMANCE_DEFAULT_CONDUCTOR_ARTIST_ID", str(conductor_id))

    settings = Settings()

    assert settings.performance_default_location_id == location_id
    assert settings.performance_default_conductor_artist_id == conductor_id


def test_max_request_body_bytes_defaults_to_one_mebibyte(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("MAX_REQUEST_BODY_BYTES", raising=False)

    assert Settings().max_request_body_bytes == 1_048_576


def test_max_request_body_bytes_can_be_overridden(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "2048")

    assert Settings().max_request_body_bytes == 2048


def test_blank_environment_values_count_as_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("SMTP_PORT", "")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("KOOFR_USER", "")

    settings = Settings()

    assert settings.smtp_port is None
    assert settings.google_client_id is None
    assert settings.koofr_user is None


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)


def test_wildcard_cors_origin_exits(monkeypatch: pytest.MonkeyPatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example,*")

    with pytest.raises(SystemExit):
        Settings()


@pytest.mark.parametrize("timezone", ["Mars/Olympus_Mons", "/etc/passwd", "../UTC"])
def test_unknown_or_malformed_timezone_exits(
    monkeypatch: pytest.MonkeyPatch, timezone: str
):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_TIMEZONE", timezone)

    with pytest.raises(SystemExit):
        Settings()


def test_known_timezone_is_accepted(monkeypatch: pytest.MonkeyPatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_TIMEZONE", "UTC")

    assert Settings().app_timezone == "UTC"


@pytest.mark.parametrize("environment", ["qa", "production"])
def test_missing_valkey_password_exits_on_qa_and_production(
    monkeypatch: pytest.MonkeyPatch, environment: str
):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)

    with pytest.raises(SystemExit):
        Settings()


@pytest.mark.parametrize("environment", ["qa", "production"])
def test_blank_valkey_password_exits_on_qa_and_production(
    monkeypatch: pytest.MonkeyPatch, environment: str
):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.setenv("VALKEY_PASSWORD", "")

    with pytest.raises(SystemExit):
        Settings()


@pytest.mark.parametrize("environment", ["qa", "production"])
def test_valkey_password_is_accepted_on_qa_and_production(
    monkeypatch: pytest.MonkeyPatch, environment: str
):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.setenv("VALKEY_PASSWORD", "s3cret")

    password = Settings().valkey_password

    assert password is not None
    assert password.get_secret_value() == "s3cret"


@pytest.mark.parametrize("environment", ["development", "test"])
def test_missing_valkey_password_is_allowed_outside_qa_and_production(
    monkeypatch: pytest.MonkeyPatch, environment: str
):
    _base_env(monkeypatch)
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.delenv("VALKEY_PASSWORD", raising=False)

    assert Settings().valkey_password is None


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SESSION_LIFETIME_MINUTES", "0"),
        ("SESSION_LIFETIME_MINUTES", "1441"),
        ("SESSION_IDLE_TIMEOUT_MINUTES", "-1"),
        ("REFRESH_TOKEN_LIFETIME_DAYS", "0"),
        ("REFRESH_TOKEN_LIFETIME_DAYS", "91"),
        ("MAIL_KILL_SWITCH_PERIOD_DAYS", "0"),
        ("MAIL_KILL_SWITCH_THRESHOLD", "0"),
        ("EMAIL_VERIFICATION_TTL_MINUTES", "0"),
        ("PASSWORD_RESET_TTL_MINUTES", "0"),
        ("KOOFR_BACKUP_RETENTION_DAYS", "0"),
        ("BACKUP_HOUR", "24"),
        ("BACKUP_HOUR", "-1"),
        ("BACKUP_MINUTE", "60"),
        ("VALKEY_PORT", "0"),
        ("VALKEY_PORT", "65536"),
    ],
)
def test_out_of_range_numeric_setting_is_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
):
    _base_env(monkeypatch)
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("variable", "value", "attribute"),
    [
        ("SESSION_LIFETIME_MINUTES", "1440", "session_lifetime_minutes"),
        ("REFRESH_TOKEN_LIFETIME_DAYS", "90", "refresh_token_lifetime_days"),
        ("BACKUP_HOUR", "23", "backup_hour"),
        ("BACKUP_MINUTE", "59", "backup_minute"),
        ("VALKEY_PORT", "65535", "valkey_port"),
    ],
)
def test_numeric_setting_accepts_its_upper_bound(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, attribute: str
):
    _base_env(monkeypatch)
    monkeypatch.setenv(variable, value)

    assert getattr(Settings(), attribute) == int(value)


def test_refresh_cookie_samesite_defaults_to_strict(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.delenv("REFRESH_COOKIE_SAMESITE", raising=False)

    assert Settings().refresh_cookie_samesite == "strict"


@pytest.mark.parametrize("value", ["strict", "lax", "none"])
def test_refresh_cookie_samesite_accepts_the_three_attributes(
    monkeypatch: pytest.MonkeyPatch, value: str
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("REFRESH_COOKIE_SAMESITE", value)

    assert Settings().refresh_cookie_samesite == value


@pytest.mark.parametrize("value", ["sometimes", "None ", "Strict"])
def test_refresh_cookie_samesite_refuses_anything_else(
    monkeypatch: pytest.MonkeyPatch, value: str
):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("REFRESH_COOKIE_SAMESITE", value)

    with pytest.raises((SystemExit, ValidationError)):
        Settings()


def test_smtp_credentials_default_to_none(monkeypatch: pytest.MonkeyPatch):
    _base_env(monkeypatch)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    settings = Settings()

    assert settings.smtp_user is None
    assert settings.smtp_password is None


def test_blank_smtp_credentials_count_as_unset(monkeypatch: pytest.MonkeyPatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASSWORD", "")

    settings = Settings()

    assert settings.smtp_user is None
    assert settings.smtp_password is None


def test_the_word_null_is_an_ordinary_smtp_value(monkeypatch: pytest.MonkeyPatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "null")
    monkeypatch.setenv("SMTP_PASSWORD", "null")

    settings = Settings()

    assert settings.smtp_user == "null"
    assert settings.smtp_password is not None
    assert settings.smtp_password.get_secret_value() == "null"


def test_credentials_are_not_printed_by_repr(monkeypatch: pytest.MonkeyPatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:db-secret@localhost/db")
    monkeypatch.setenv("SECRET_KEY", "signing-secret-" + "x" * 32)
    monkeypatch.setenv("SMTP_USER", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-secret")
    monkeypatch.setenv("VALKEY_PASSWORD", "valkey-secret")
    monkeypatch.setenv("KOOFR_PASSWORD", "koofr-secret")

    rendered = repr(Settings())

    for secret in (
        "db-secret",
        "signing-secret",
        "smtp-secret",
        "valkey-secret",
        "koofr-secret",
    ):
        assert secret not in rendered


@pytest.mark.parametrize(
    ("name", "value"),
    [("SMTP_USER", "mailer"), ("SMTP_PASSWORD", "smtp-secret")],
    ids=["only-user", "only-password"],
)
def test_a_single_smtp_credential_exits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
    value: str,
):
    _base_env(monkeypatch)
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv(name, value)

    with pytest.raises(SystemExit):
        Settings()

    assert "SMTP_USER and SMTP_PASSWORD" in capsys.readouterr().err


def test_both_smtp_credentials_are_accepted(monkeypatch: pytest.MonkeyPatch):
    _base_env(monkeypatch)
    monkeypatch.setenv("SMTP_USER", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-secret")

    assert Settings().smtp_user == "mailer"
