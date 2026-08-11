from datetime import UTC, datetime
from typing import overload
from zoneinfo import ZoneInfo

from app.core.config import get_settings

# SQLite has no timezone-aware storage -- every datetime read back from the
# DB comes back naive, even though every write goes through datetime.now(UTC).
# Comparing a naive value against an aware one raises TypeError, so any code
# comparing a stored timestamp against "now" needs this normalization first.
#
# This applies ONLY to genuinely UTC audit columns (created_at/updated_at,
# token/session timestamps) that are actually written via datetime.now(UTC).
# It must NOT be used on user-entered wall-clock fields like
# Performance.schedule -- those are naive local time in Settings.app_timezone
# (mirroring Legacy's Carbon under config('app.timezone')), not UTC. See
# local_now() below for that case.


@overload
def ensure_tz_aware(dt: datetime) -> datetime: ...
@overload
def ensure_tz_aware(dt: None) -> None: ...
def ensure_tz_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def local_now() -> datetime:
    """Naive wall-clock 'now' in Settings.app_timezone (default
    Europe/Vienna), for comparison against naive wall-clock columns like
    Performance.schedule/PerformanceRehearsal.schedule (see module docstring
    above). Mirrors Legacy's Carbon::now() under config('app.timezone').
    Deliberately NOT datetime.now(UTC) or plain datetime.now() -- the
    container OS runs in UTC, not Vienna, so a bare local "now" would
    silently be off by the configured zone's UTC offset (1-2h depending on
    DST), exactly like the bug this replaced."""
    return datetime.now(ZoneInfo(get_settings().app_timezone)).replace(tzinfo=None)
