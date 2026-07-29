from datetime import UTC, datetime
from typing import overload

# SQLite has no timezone-aware storage -- every datetime read back from the
# DB comes back naive, even though every write goes through datetime.now(UTC).
# Comparing a naive value against an aware one raises TypeError, so any code
# comparing a stored timestamp against "now" needs this normalization first.


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
