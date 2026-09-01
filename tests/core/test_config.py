import pytest

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
    monkeypatch.delenv("PASSWORD_MIN_LENGTH", raising=False)

    settings = Settings()

    assert settings.secret_key == "x" * 32
    assert settings.session_lifetime_minutes == 15
    assert settings.session_idle_timeout_minutes == 120
    assert settings.refresh_token_lifetime_days == 7
    assert settings.password_min_length == 8


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
    assert settings.koofr_password == "secret"


def test_performance_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PERFORMANCE_DEFAULT_LOCATION_ID", raising=False)
    monkeypatch.delenv("PERFORMANCE_DEFAULT_CONDUCTOR_ARTIST_ID", raising=False)

    settings = Settings()

    assert settings.performance_default_location_id == 1
    assert settings.performance_default_conductor_artist_id == 95


def test_performance_defaults_can_be_overridden(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PERFORMANCE_DEFAULT_LOCATION_ID", "2")
    monkeypatch.setenv("PERFORMANCE_DEFAULT_CONDUCTOR_ARTIST_ID", "7")

    settings = Settings()

    assert settings.performance_default_location_id == 2
    assert settings.performance_default_conductor_artist_id == 7
