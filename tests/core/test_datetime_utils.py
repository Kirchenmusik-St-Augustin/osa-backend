from datetime import UTC, datetime, timezone

from app.core.datetime_utils import ensure_tz_aware


def test_returns_none_for_none():
    assert ensure_tz_aware(None) is None


def test_attaches_utc_to_a_naive_datetime():
    naive = datetime(2026, 7, 29, 12, 0, 0)  # noqa: DTZ001 -- naive on purpose
    result = ensure_tz_aware(naive)
    assert result == datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)


def test_leaves_an_already_aware_datetime_untouched():
    aware = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.min)
    assert ensure_tz_aware(aware) is aware
