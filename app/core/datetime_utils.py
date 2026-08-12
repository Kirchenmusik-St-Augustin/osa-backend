from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, overload
from zoneinfo import ZoneInfo

from pydantic import BeforeValidator

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


# The ONE place a genuinely-UTC audit/event field is declared in an output
# schema -- use this instead of a bare `datetime` for every field mirroring
# the categories above (created_at/updated_at, token/session timestamps,
# email_verified_at/auth_lastsignal/deleted_at, ...). Runs ensure_tz_aware()
# as a pydantic BeforeValidator, so the naive value SQLite hands back is
# stamped UTC before pydantic ever serializes it -- FastAPI's JSON response
# then carries a real "+00:00" offset instead of an offset-free string.
# Without this, the frontend's offset-aware formatters (dateFormat.ts's
# formatUtcDateTime/formatTimeOnly/formatDateOnly) silently misread the
# naive string as browser-local time via `new Date(iso)`, displaying the
# value shifted by the viewer's UTC offset (1-2h under Vienna's CET/CEST) --
# exactly the class of bug local_now() below already fixed for wall-clock
# fields. A schema field forgetting to wrap a UTC column in this type is a
# repeat of that same bug, just for audit/event timestamps instead of
# business timestamps -- do not assign a bare DB datetime to a bare
# `datetime`-typed output field for any of the categories above.
UtcDatetime = Annotated[datetime, BeforeValidator(ensure_tz_aware)]


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


def local_day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """Returns the [start, end) UTC instant bounds of one local calendar day
    in Settings.app_timezone (default Europe/Vienna) -- for range-filtering
    genuinely-UTC audit columns like RequestLog.created_at by a local
    calendar day (see module docstring above for the naive-local vs. UTC
    column distinction; contrast with local_now() above, which is for naive
    wall-clock BUSINESS columns instead, not this case).

    DST-safe: builds the local midnight-to-midnight boundary through
    ZoneInfo instead of a fixed 24h timedelta -- Vienna's two annual DST
    transition days are 23h (spring-forward) or 25h (fall-back) long, never
    exactly 24h."""
    tz = ZoneInfo(get_settings().app_timezone)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
