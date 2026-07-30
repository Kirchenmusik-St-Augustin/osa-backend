import pytest

from app.core.config import Settings


def test_valid_settings_parses_cors_origins_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    settings = Settings()

    assert settings.cors_origins_list == ["https://a.example", "https://b.example"]


def test_missing_app_environment_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    with pytest.raises(SystemExit):
        Settings()


def test_invalid_app_environment_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "not-a-real-environment")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    with pytest.raises(SystemExit):
        Settings()


def test_missing_cors_origins_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    with pytest.raises(SystemExit):
        Settings()


def test_blank_cors_origins_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", " , ")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

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
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(SystemExit):
        Settings()


def test_too_short_secret_key_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "too-short")

    with pytest.raises(SystemExit):
        Settings()


def test_app_timezone_defaults_to_europe_vienna():
    assert Settings().app_timezone == "Europe/Vienna"


def test_app_timezone_can_be_overridden(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")

    assert Settings().app_timezone == "America/New_York"


def test_valid_secret_key_and_tier2_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.delenv("SESSION_LIFETIME_MINUTES", raising=False)
    monkeypatch.delenv("SESSION_IDLE_TIMEOUT_MINUTES", raising=False)
    monkeypatch.delenv("REFRESH_TOKEN_LIFETIME_DAYS", raising=False)
    monkeypatch.delenv("PASSWORD_MIN_LENGTH", raising=False)

    settings = Settings()

    assert settings.secret_key == "x" * 32
    assert settings.session_lifetime_minutes == 15
    assert settings.session_idle_timeout_minutes == 120
    assert settings.refresh_token_lifetime_days == 7
    assert settings.password_min_length == 8
