import logging
from datetime import datetime

from app.core.datetime_utils import get_app_timezone


class _AppTimezoneFormatter(logging.Formatter):
    """Formats %(asctime)s in Settings.app_timezone instead of the
    container OS clock (logging.Formatter's default converter reads
    time.localtime(), i.e. the container's system timezone -- UTC here,
    since neither the Dockerfile nor any quadlet sets TZ=). Keeps logging
    on the same "resolve explicitly via Settings.app_timezone, never trust
    the OS zone" footing as every other datetime concern in this codebase
    (see datetime_utils.py's module docstring) -- this was the one place
    still silently relying on it."""

    def formatTime(  # noqa: N802 -- overrides logging.Formatter's own camelCase method name
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:
        dt = datetime.fromtimestamp(record.created, tz=get_app_timezone())
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S%z")


def setup_logging() -> None:
    """Configure root logging once, at process start."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        _AppTimezoneFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
