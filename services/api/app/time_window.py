"""
services/api/app/time_window.py
Resolves the reporting window for analytics endpoints.

Endpoints historically accepted only `period_days` (window = now - N days → now). The
dashboard's time-range picker also needs sub-day presets ("last 15 minutes") and absolute
custom ranges, so endpoints additionally accept optional ISO-8601 `start` / `end`. When
`start` is given it takes precedence; `period_days` remains the backward-compatible default.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

# Matches the longest look-back any analytics endpoint supports.
MAX_WINDOW = timedelta(days=366)


def _as_utc(value: datetime) -> datetime:
    """Treats naive datetimes as UTC and normalises aware ones to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_window(
    period_days: int,
    start: datetime | None = None,
    end: datetime | None = None,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """
    Returns the (start, end) window in UTC.

    - `start` given: [start, end or now]. `end` is capped at now (no future data exists).
    - otherwise: [now - period_days, now].

    Raises HTTP 422 when the window is empty/reversed or longer than MAX_WINDOW.
    """
    now = _as_utc(now) if now else datetime.now(timezone.utc)
    if start is None:
        if end is not None:
            raise HTTPException(status_code=422, detail="`end` requires `start`.")
        return now - timedelta(days=period_days), now

    window_start = _as_utc(start)
    window_end = min(_as_utc(end), now) if end is not None else now
    if window_start >= window_end:
        raise HTTPException(status_code=422, detail="`start` must be before `end` (and before now).")
    if window_end - window_start > MAX_WINDOW:
        raise HTTPException(status_code=422, detail="Time window is too long (max 366 days).")
    return window_start, window_end


def day_floor(value: datetime) -> datetime:
    """
    Start of the UTC day containing `value`. Daily rollup rows are keyed by midnight, so a
    window starting mid-day must include that day's row to be counted at all.
    """
    return value.replace(hour=0, minute=0, second=0, microsecond=0)
