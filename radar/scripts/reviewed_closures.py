"""Narrow, source-reviewed Taiwan closure correction pending full PR5 calendar.

Only the 2026-10-23 through 2026-10-27 reopening window changes freshness.
Calendar facts never certify a provider bar or refresh its collection receipt.
"""
import datetime as dt
from zoneinfo import ZoneInfo


SOURCES = (
    'https://www.twse.com.tw/staticFiles/news/news/tsecnews/8a8216d6a0fa351b01a1638507940202.pdf',
    'https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=html',
)
TW_NON_SESSIONS = frozenset(('2026-10-23', '2026-10-24', '2026-10-25', '2026-10-26'))


def known_closed(market, day):
    return market == '台股' and day in TW_NON_SESSIONS


def expected_close(market, now):
    """Return an exact required close only within this reviewed reopening window."""
    if market != '台股' or now.tzinfo is None:
        return None
    local = now.astimezone(ZoneInfo('Asia/Taipei'))
    if not '2026-10-23' <= local.date().isoformat() <= '2026-10-27':
        return None
    reopening_close = dt.datetime(2026, 10, 27, 13, 30, tzinfo=ZoneInfo('Asia/Taipei'))
    return '2026-10-22' if local < reopening_close else '2026-10-27'


def completed_bars(record, bars, market, now, *, symbol=None):
    """Discard proven false dates, requiring observed and provider-proven real bars.

Do not substitute 10/21 when 10/22 is absent, skip a normal trading-day tail,
or let a legacy closed marker replace the original provider session evidence.
Known false dates are also removed from later history, so they never enter
return calculations after the market reopens. The original record stays intact.
"""
    from equity_close_proof import record_bar_final
    expected = expected_close(market, now)
    false_dates = [bar for bar in bars if known_closed(market, bar[0])]
    if expected is None and not false_dates:
        return bars
    local_day = now.astimezone(ZoneInfo('Asia/Taipei')).date().isoformat()
    if record.get('asOf', '') > local_day:
        return []
    if expected and any(bar[0] > expected and not known_closed(market, bar[0]) for bar in bars):
        return []
    selected = [bar for bar in bars if not known_closed(market, bar[0])]
    if not selected or (expected and selected[-1][0] != expected):
        return []
    if false_dates or expected:
        timestamps = record.get('barTimestamps')
        day = selected[-1][0]
        if not isinstance(timestamps, dict) or not record_bar_final(record, day, symbol=symbol, now=now):
            return []
        if expected:
            # Advancing now cannot upgrade a payload received before the real
            # Taiwan close, nor an erroneous early provider session end.
            official_close = dt.datetime.fromisoformat(expected+'T13:30:00').replace(
                tzinfo=ZoneInfo('Asia/Taipei')).timestamp()
            try:
                received = dt.datetime.fromisoformat(record['receivedAt'])
                if (received.tzinfo is None or received.timestamp() < official_close
                        or record['finality']['end'] < official_close):
                    return []
            except (KeyError, TypeError, ValueError, OverflowError, OSError):
                return []
    return selected
