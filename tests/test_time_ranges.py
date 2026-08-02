from datetime import UTC, datetime, timedelta

import pytest

from energy_optimizer.time_ranges import resolve_history_range


def test_resolve_recent_days_range():
    now = datetime(2026, 8, 10, 3, 0, tzinfo=UTC)
    start, end = resolve_history_range(
        from_value=None,
        to_value=None,
        days=7,
        timezone_name="Australia/Brisbane",
        now=now,
    )
    assert end == now
    assert start == now - timedelta(days=7)


def test_explicit_export_dates_are_inclusive_local_dates():
    start, end = resolve_history_range(
        from_value="2026-08-01",
        to_value="2026-08-02",
        days=None,
        timezone_name="Australia/Brisbane",
    )
    assert start.hour == 0
    assert end.hour == 23
    assert end.microsecond == 999999


def test_days_conflicts_with_explicit_range():
    with pytest.raises(ValueError, match="cannot be combined"):
        resolve_history_range(
            from_value="2026-08-01",
            to_value=None,
            days=1,
            timezone_name="Australia/Brisbane",
        )
