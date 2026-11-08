"""Issuer-local earnings dates at the immutable data snapshot clock.

A scheduled date is not proof that a report was published. These helpers only
compare calendar dates; they never infer a release time from a time-note.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# Same defaults as the frozen Notion contract and the browser calendar.
MARKET_TIMEZONES = {
    'A股': 'Asia/Shanghai', '美股': 'America/New_York',
    '港股': 'Asia/Hong_Kong', '台股': 'Asia/Taipei',
    '韩股': 'Asia/Seoul', '日股': 'Asia/Tokyo', '欧股': 'Europe/Paris',
}


def issuer_today(clock, market, timezone_name=None, *, market_timezones=None):
    """Return the issuer's date, or None when clock/zone cannot be resolved.

    Invalid explicit zones follow the existing market-default contract. The
    caller remains responsible for retaining the existing timezone warning.
    Never interpret a naive clock using the machine's local timezone.
    """
    try:
        instant = clock if isinstance(clock, dt.datetime) else dt.datetime.fromisoformat(str(clock).replace('Z', '+00:00'))
        if instant.tzinfo is None or instant.utcoffset() is None:
            return None
    except (ValueError, TypeError, OverflowError):
        return None
    defaults = MARKET_TIMEZONES if market_timezones is None else market_timezones
    for name in (timezone_name, defaults.get(market)):
        if not isinstance(name, str) or not name:
            continue
        try:
            return instant.astimezone(ZoneInfo(name)).date()
        except (ZoneInfoNotFoundError, ValueError, OverflowError):
            continue
    return None


def days_until(company, clock, *, legacy_today=None):
    """Calendar-day distance, with an explicit date-only legacy interface.

    Missing-clock legacy data may supply its declared date. A present but
    invalid clock never falls back to that date or the current wall clock.
    """
    try:
        scheduled = dt.date.fromisoformat(company.get('next') or '')
    except (ValueError, TypeError):
        return None
    local_day = issuer_today(clock, company.get('mkt'), (company.get('earnings') or {}).get('timezone'))
    if clock is None and legacy_today is not None:
        try:
            local_day = dt.date.fromisoformat(str(legacy_today))
        except (ValueError, TypeError):
            return None
    return (scheduled - local_day).days if local_day is not None else None


def within_earnings_window(company, clock, *, days=14, legacy_today=None):
    distance = days_until(company, clock, legacy_today=legacy_today)
    return distance is not None and 0 <= distance <= days
