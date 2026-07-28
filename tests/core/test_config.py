import pytest

from app.core.config import Settings


def test_valid_settings_parses_cors_origins_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    settings = Settings()

    assert settings.cors_origins_list == ["https://a.example", "https://b.example"]


def test_missing_app_environment_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    with pytest.raises(SystemExit):
        Settings()


def test_invalid_app_environment_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "not-a-real-environment")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    with pytest.raises(SystemExit):
        Settings()


def test_missing_cors_origins_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    with pytest.raises(SystemExit):
        Settings()


def test_blank_cors_origins_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", " , ")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

    with pytest.raises(SystemExit):
        Settings()


def test_missing_database_url_exits(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit):
        Settings()
