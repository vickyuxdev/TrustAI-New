"""Unit tests for app.time_window — the reporting-window resolver used by analytics endpoints."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.time_window import day_floor, resolve_window

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def test_period_days_default_window():
    """Without start/end the window is the classic now - period_days → now."""
    start, end = resolve_window(7, now=NOW)
    assert end == NOW
    assert start == NOW - timedelta(days=7)


def test_explicit_start_end_overrides_period_days():
    """An explicit window wins over period_days, including sub-day ranges."""
    s = NOW - timedelta(minutes=15)
    start, end = resolve_window(7, s, NOW, now=NOW)
    assert (start, end) == (s, NOW)


def test_start_without_end_runs_to_now():
    """A start alone means 'from start until now'."""
    s = NOW - timedelta(hours=1)
    assert resolve_window(1, s, None, now=NOW) == (s, NOW)


def test_end_in_future_is_capped_at_now():
    """No data exists after now, so a future end is clamped."""
    s = NOW - timedelta(days=1)
    _, end = resolve_window(1, s, NOW + timedelta(days=3), now=NOW)
    assert end == NOW


def test_naive_datetimes_are_treated_as_utc():
    """Clients that omit the offset get UTC semantics rather than server-local time."""
    naive = datetime(2026, 10, 29, 8, 0)
    start, _ = resolve_window(1, naive, None, now=NOW)
    assert start == naive.replace(tzinfo=timezone.utc)


def test_offset_datetimes_are_normalised_to_utc():
    """A +05:30 start is converted, not reinterpreted."""
    ist = timezone(timedelta(hours=5, minutes=30))
    s = datetime(2026, 10, 30, 10, 0, tzinfo=ist)
    start, _ = resolve_window(1, s, None, now=NOW)
    assert start == datetime(2026, 10, 30, 4, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "start,end",
    [
        (NOW, NOW - timedelta(hours=1)),                     # reversed
        (NOW, NOW),                                          # empty
        (NOW + timedelta(hours=1), None),                    # starts in the future
        (NOW - timedelta(days=400), NOW),                    # too long
    ],
)
def test_invalid_windows_are_rejected(start, end):
    """Empty, reversed, future or over-long windows return HTTP 422."""
    with pytest.raises(HTTPException) as exc:
        resolve_window(7, start, end, now=NOW)
    assert exc.value.status_code == 422


def test_end_without_start_is_rejected():
    """`end` alone is ambiguous, so it is refused instead of silently ignored."""
    with pytest.raises(HTTPException):
        resolve_window(7, None, NOW, now=NOW)


def test_day_floor_aligns_to_midnight():
    """Daily rollup rows are keyed at midnight UTC."""
    assert day_floor(datetime(2026, 10, 30, 17, 45, 12, 9, tzinfo=timezone.utc)) == datetime(
        2026, 10, 30, tzinfo=timezone.utc
    )
