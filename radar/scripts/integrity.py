"""Conservative data gates. Age tolerance is not an exchange-calendar guarantee."""
import datetime as dt
import math
from zoneinfo import ZoneInfo

ZONES = {'A股': 'Asia/Shanghai', '港股': 'Asia/Hong_Kong', '美股': 'America/New_York',
         '台股': 'Asia/Taipei', '韩股': 'Asia/Seoul', '日股': 'Asia/Tokyo', '欧股': 'Europe/Paris'}


def number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def observation_time(kind, record):
    """Comparable provider observation, never the collection receipt or month label."""
    if not isinstance(record, dict) or record.get('schemaVersion') != 2:
        return None
    try:
        if kind == 'quote':
            timestamp = record.get('regularMarketTime')
            if not number(timestamp) or timestamp <= 0:
                return None
            return dt.datetime.fromtimestamp(timestamp, dt.UTC)
        raw = record.get('date' if kind == 'index' else 'asOf')
        date = dt.date.fromisoformat(raw)
        if date.isoformat() != raw:
            return None
        if kind == 'daily':
            if not valid_bars(record.get('bars')) or record['bars'][-1][0] != raw:
                return None
        if kind == 'ratio':
            current = record.get('current')
            bars = record.get('bars')
            if (not isinstance(current, dict) or current.get('date') != raw
                    or current.get('src') != record.get('src') or not current.get('src')
                    or not number(current.get('close')) or current['close'] <= 0
                    or not isinstance(bars, list) or not bars):
                return None
            previous = ''
            for bar in bars:
                if (not isinstance(bar, list) or len(bar) != 2
                        or dt.date.fromisoformat(bar[0] + '-01').isoformat()[:7] != bar[0]
                        or bar[0] <= previous or not number(bar[1]) or bar[1] <= 0):
                    return None
                previous = bar[0]
            if bars[-1] != [raw[:7], current['close']]:
                return None
        return dt.datetime.combine(date, dt.time(), dt.UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None


def fresh_record(record, now, date=None, market='A股'):
    if not isinstance(record, dict) or record.get('schemaVersion') != 2:
        return False
    try:
        received = dt.datetime.fromisoformat(record['receivedAt'])
        if received.tzinfo is None or not 0 <= (now - received).total_seconds() <= 36 * 3600:
            return False
        if date is not None:
            age = (now.astimezone(ZoneInfo(ZONES[market])).date() - dt.date.fromisoformat(date)).days
            if not 0 <= age <= 4:
                return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def valid_bars(bars):
    if not isinstance(bars, list) or not bars:
        return False
    previous = ''
    for b in bars:
        if not isinstance(b, list) or len(b) < 4:
            return False
        try:
            dt.date.fromisoformat(b[0])
        except (TypeError, ValueError):
            return False
        if b[0] <= previous or not number(b[1]) or b[1] <= 0:
            return False
        if b[2] is not None and (not number(b[2]) or b[2] <= 0):
            return False
        if b[3] is not None and (not number(b[3]) or b[3] < b[1]):
            return False
        previous = b[0]
    return True


def financial_status(fin, today):
    if not fin or not fin.get('source_url') or not fin.get('source_name'):
        return 'missing_source'
    try:
        end, published, checked = [dt.date.fromisoformat(fin[k]) for k in ('period_end', 'published_at', 'verified_at')]
    except (KeyError, TypeError, ValueError):
        return 'missing_dates'
    if not end <= published <= checked <= today:
        return 'invalid_dates'
    if (today - end).days > 200 or (today - checked).days > 100:
        return 'stale'
    if fin.get('basis') != 'single_quarter':
        return 'unsupported_period_basis'
    return 'verified'


def release_blockers(D):
    blockers = list(D['meta'].get('blockers', []))
    if D['meta'].get('fixture'):
        blockers.append('synthetic_fixture_not_publishable')
    if D['meta'].get('offline'):
        blockers.append('offline_not_publishable')
    return sorted(set(blockers))
