"""Typed application configuration, sourced from environment variables.

Access exclusively via get_settings() (never instantiate Settings()
directly) -- it is the only path that keeps the lru_cache and its per-test
reset fixture (see tests/conftest.py) in sync.

Tier 1 (boot-critical, validated in _validate_tier1 below): APP_ENVIRONMENT,
CORS_ORIGINS, DATABASE_URL, SECRET_KEY.

Tier 2 (optional, defaults applied, no boot-time validation): session/JWT
lifetimes, mail sender identity, registration/mail-kill-switch tuning --
sane defaults (several taken straight from Legacy's config/mail.php and
config/osa.php) so a deployment that never touches these features still
boots.

Tier 3 (feature-required, no default -- checked at first actual use via
require_setting(), not at boot): SMTP_HOST/SMTP_PORT, GOOGLE_CLIENT_ID,
FRONTEND_VERIFY_EMAIL_URL, FRONTEND_RESET_PASSWORD_URL. A deployment that
never sends email or never enables Google Login must not be forced to
configure these just to boot; the first actual attempt to use the feature
raises a normal RuntimeError instead of exiting the process.
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

    # Tier 2 -- optional with defaults, no boot-time validation.
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

    # Tier 2 (mail) -- defaults taken from Legacy's config/mail.php /
    # config/osa.php so the migrated values stay identical.
    smtp_from_email: str = Field(
        default="no-reply@hochamt.at", validation_alias="SMTP_FROM_EMAIL"
    )
    smtp_from_name: str = Field(
        default="Kirchenmusik St. Augustin", validation_alias="SMTP_FROM_NAME"
    )
    # "null" (not "") mirrors the historical env convention: an explicit
    # sentinel meaning "no SMTP auth", checked via `.lower() != "null"`.
    smtp_user: str = Field(default="null", validation_alias="SMTP_USER")
    smtp_password: str = Field(default="null", validation_alias="SMTP_PASSWORD")
    mail_disponent: str = Field(
        default="einteilung@hochamt.at", validation_alias="MAIL_DISPONENT"
    )
    mail_kill_switch_period_days: int = Field(
        default=30, validation_alias="MAIL_KILL_SWITCH_PERIOD_DAYS"
    )
    mail_kill_switch_threshold: int = Field(
        default=950, validation_alias="MAIL_KILL_SWITCH_THRESHOLD"
    )
    email_verification_ttl_minutes: int = Field(
        default=60, validation_alias="EMAIL_VERIFICATION_TTL_MINUTES"
    )
    password_reset_ttl_minutes: int = Field(
        default=60, validation_alias="PASSWORD_RESET_TTL_MINUTES"
    )

    # Tier 3 -- feature-required, no default, checked at first use via
    # require_setting() below.
    smtp_host: str | None = Field(default=None, validation_alias="SMTP_HOST")
    smtp_port: int | None = Field(default=None, validation_alias="SMTP_PORT")
    google_client_id: str | None = Field(
        default=None, validation_alias="GOOGLE_CLIENT_ID"
    )
    frontend_verify_email_url: str | None = Field(
        default=None, validation_alias="FRONTEND_VERIFY_EMAIL_URL"
    )
    frontend_reset_password_url: str | None = Field(
        default=None, validation_alias="FRONTEND_RESET_PASSWORD_URL"
    )

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


def require_setting[T](value: T | None, env_var: str) -> T:
    """Raise for a Tier 3 (feature-required) setting that is unset.

    Unlike Tier 1's _fail() (which aborts the process at boot), this raises
    a normal exception at first use -- the process itself must stay up even
    if one feature (e.g. email, Google Login) is unconfigured.
    """
    if value is None:
        msg = f"{env_var} is not set."
        raise RuntimeError(msg)
    return value
