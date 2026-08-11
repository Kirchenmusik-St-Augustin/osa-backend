from typing import cast

from app.core.config import get_settings


def get_app_environment() -> str:
    # Settings._validate_tier1 already exits the process if app_environment
    # is unset, so by the time get_settings() returns, it is guaranteed
    # non-None (see app/core/config.py's Tier 1 fields).
    return cast("str", get_settings().app_environment)
