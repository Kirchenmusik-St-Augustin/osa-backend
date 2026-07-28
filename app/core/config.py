"""Typed application configuration, sourced from environment variables.

Access exclusively via get_settings() (never instantiate Settings()
directly) -- it is the only path that keeps the lru_cache and its per-test
reset fixture (see tests/conftest.py) in sync.

Tier 1 (boot-critical, validated in _validate_tier1 below): APP_ENVIRONMENT,
CORS_ORIGINS, DATABASE_URL, SECRET_KEY.

Tier 2 (optional, defaults applied, no boot-time validation): session/JWT
lifetimes -- a deployment that never boots the Auth slice's tests still
gets sane defaults, matching the vb-fastapi-vue sister project's values.
"""

import sys
from functools import lru_cache
from typing import NoReturn

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_ENVIRONMENTS = frozenset({"development", "test", "qa", "production"})


def _fail(message: str) -> NoReturn:
    sys.stderr.write(f"FATAL: {message} Aborting.\n")
    sys.stderr.flush()
    sys.exit(1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_environment: str | None = Field(
        default=None, validation_alias="APP_ENVIRONMENT"
    )
    cors_origins: str | None = Field(default=None, validation_alias="CORS_ORIGINS")
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    secret_key: str | None = Field(default=None, validation_alias="SECRET_KEY")

    # Tier 2 -- optional with defaults, no boot-time validation. Defaults
    # match vb-api's own values exactly (sister-project parity default).
    session_lifetime_minutes: int = Field(
        default=15, validation_alias="SESSION_LIFETIME_MINUTES"
    )
    session_idle_timeout_minutes: int = Field(
        default=120, validation_alias="SESSION_IDLE_TIMEOUT_MINUTES"
    )
    refresh_token_lifetime_days: int = Field(
        default=7, validation_alias="REFRESH_TOKEN_LIFETIME_DAYS"
    )
    password_min_length: int = Field(default=8, validation_alias="PASSWORD_MIN_LENGTH")

    @model_validator(mode="after")
    def _validate_tier1(self) -> "Settings":
        if not self.app_environment or self.app_environment not in _VALID_ENVIRONMENTS:
            _fail(
                f"APP_ENVIRONMENT='{self.app_environment}' invalid or unset. "
                f"Valid values: {sorted(_VALID_ENVIRONMENTS)}."
            )
        if not self.cors_origins_list:
            _fail("CORS_ORIGINS is not set or contains no valid origins.")
        if not self.database_url:
            _fail("DATABASE_URL is not set.")
        if not self.secret_key:
            _fail("SECRET_KEY is not set.")
        if len(self.secret_key) < 32:
            _fail("SECRET_KEY must be at least 32 characters long.")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in (self.cors_origins or "").split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
