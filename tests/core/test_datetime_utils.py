from datetime import UTC, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.config import get_settings
from app.core.datetime_utils import ensure_tz_aware, local_now


def test_returns_none_for_none():
    assert ensure_tz_aware(None) is None


def test_attaches_utc_to_a_naive_datetime():
    naive = datetime(2026, 7, 29, 12, 0, 0)  # noqa: DTZ001 -- naive on purpose
    result = ensure_tz_aware(naive)
    assert result == datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


def test_leaves_an_already_aware_datetime_untouched():
    aware = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.min)
    assert ensure_tz_aware(aware) is aware


def test_local_now_is_naive():
    assert local_now().tzinfo is None


def test_local_now_matches_the_configured_zone_not_the_container_clock():
    """Regression: the osa-backend container OS runs in UTC (confirmed via
    `podman exec osa-backend date`), so a bare datetime.now() would silently
    be off by the Vienna/UTC offset (1-2h depending on DST) -- exactly the
    bug that shifted the July 2026 calendar by +2h before local_now() was
    introduced. local_now() must reflect Settings.app_timezone's real
    offset, not the container's system clock."""
    expected = datetime.now(ZoneInfo("Europe/Vienna")).replace(tzinfo=None)
    actual = local_now()
    assert abs((actual - expected).total_seconds()) < 5


def test_local_now_honors_a_configured_app_timezone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    get_settings.cache_clear()

    expected = datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    actual = local_now()
    assert abs((actual - expected).total_seconds()) < 5
