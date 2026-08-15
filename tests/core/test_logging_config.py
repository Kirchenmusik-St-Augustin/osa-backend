import logging
from datetime import UTC, datetime

import pytest

from app.core import logging_config
from app.core.config import get_settings
from app.core.logging_config import setup_logging


def test_setup_logging_sets_root_level_info():
    setup_logging()

    assert logging.getLogger().level == logging.INFO


def test_formatter_renders_asctime_in_app_timezone(monkeypatch: pytest.MonkeyPatch):
    """Regression: log timestamps must follow Settings.app_timezone, not
    the container OS clock (UTC here, since no TZ= is set anywhere) --
    this was the one place still silently relying on the OS zone."""
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    get_settings.cache_clear()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.created = datetime(2026, 1, 1, 12, 0, tzinfo=UTC).timestamp()

    rendered = logging_config._AppTimezoneFormatter().formatTime(record)

    assert "07:00" in rendered  # UTC-5 (EST, kein DST im Jänner)


def test_setup_logging_installs_the_app_timezone_formatter():
    setup_logging()

    root = logging.getLogger()
    assert any(
        isinstance(handler.formatter, logging_config._AppTimezoneFormatter)
        for handler in root.handlers
    )
