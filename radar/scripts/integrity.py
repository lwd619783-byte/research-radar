"""Conservative data gates. Age tolerance is not an exchange-calendar guarantee."""
import datetime as dt
import math
import re
from urllib.parse import urlsplit
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
    if fin.get('basis') not in ('single_quarter', 'half_year', 'cumulative', 'annual'):
        return 'unsupported_period_basis'
    required = ('currency', 'accounting_basis', 'fiscal_year', 'fiscal_period',
                'profit_metric', 'revenue_scope', 'profit_scope', 'margin_scope',
                'report_status', 'profit_comparison', 'derivation', 'review_note')
    if not all(isinstance(fin.get(k), str) and fin[k].strip() for k in required):
        return 'missing_scope'
    urls = fin.get('source_urls')
    if not isinstance(urls, list) or not urls or fin['source_url'] not in urls:
        return 'missing_source_set'
    for url in urls:
        if not isinstance(url, str): return 'invalid_source'
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password:
            return 'invalid_source'
    if not re.fullmatch(r'[A-Z]{3}', fin['currency']):
        return 'invalid_currency'
    if fin['report_status'] not in ('final', 'preliminary', 'revenue_only'):
        return 'invalid_report_status'
    if fin['profit_comparison'] not in ('comparable', 'turnaround', 'loss_base', 'not_disclosed', 'one_off'):
        return 'invalid_profit_comparison'
    if fin['derivation'] not in ('reported', 'cumulative_difference'):
        return 'invalid_derivation'
    if fin['derivation'] == 'cumulative_difference' and (len(set(urls)) < 2 or not fin.get('calculation_note')):
        return 'missing_derivation_evidence'
    if fin.get('conditions') and not fin.get('conditions_reviewed'):
        return 'conditions_unreviewed'
    return 'verified'


def pe_status(value):
    if value is None: return 'missing'
    if not number(value): return 'invalid'
    return 'available' if value > 0 else 'nonpositive'


def fx_bar_final(day, timestamp, timezone, session, received_at):
    """Provider session boundaries, not a matching calendar date, prove finality."""
    try:
        if not isinstance(session, dict) or session.get('method') != 'provider-session-boundary':
            return False
        start, end = session['start'], session['end']
        if not all(number(x) and x > 0 for x in (timestamp, start, end)) or not 0 < end-start <= 26*3600:
            return False
        received = dt.datetime.fromisoformat(received_at)
        if received.tzinfo is None or max(timestamp, start) > received.timestamp():
            return False
        zone = ZoneInfo(timezone)
        date = dt.datetime.fromtimestamp(timestamp, zone).date().isoformat()
        if date != day:
            return False
        if timestamp < start:
            return day < dt.datetime.fromtimestamp(start, zone).date().isoformat()
        return timestamp < end and received.timestamp() >= end
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return False


def dated_fx(record, currency, day, now):
    """Select the exact observed day; never backfill with a future/nearest rate."""
    if not day or not isinstance(record, dict) or not fresh_record(record, now, day):
        return None
    if (record.get('currency') != currency or record.get('src') != 'yahoo'
            or record.get('priceBasis') != 'daily-close' or record.get('direction') != 'USD-to-local'):
        return None
    if 'rates' in record:
        rates = record['rates']
        if not isinstance(rates, list): return None
        previous = ''
        selected = None
        for row in rates:
            if not isinstance(row, list) or len(row) != 3: return None
            try:
                if dt.date.fromisoformat(row[0]).isoformat() != row[0] or row[0] <= previous: return None
            except (ValueError, TypeError): return None
            if not number(row[1]) or row[1] <= 0 or not number(row[2]) or row[2] <= 0: return None
            expected = 1 / row[2] if currency == 'EUR' else row[2]
            if not math.isclose(row[1], expected, rel_tol=1e-12): return None
            timestamps = record.get('rateTimestamps')
            if not isinstance(timestamps, dict) or not fx_bar_final(
                    row[0], timestamps.get(row[0]), record.get('timezone'),
                    record.get('finality'), record.get('receivedAt')):
                return None
            if row[0] == day: selected = row
            previous = row[0]
        if selected is None: return None
        value = selected[1]
    else:
        # Old schemaVersion=2 values came from realtime metadata; a same-day
        # date/receipt does not turn them into a confirmed historical close.
        return None
    return {'value': value, 'asOf': day, 'src': record.get('src'),
            'receivedAt': record.get('receivedAt'), 'direction': 'USD-to-local',
            'finality': {**record['finality'], 'barTimestamp': record['rateTimestamps'][day],
                         'timezone': record['timezone']}}


def release_blockers(D):
    blockers = list(D['meta'].get('blockers', []))
    if D['meta'].get('fixture'):
        blockers.append('synthetic_fixture_not_publishable')
    if D['meta'].get('reviewPreview'):
        blockers.append('local_review_not_publishable')
    if D['meta'].get('offline'):
        blockers.append('offline_not_publishable')
    return sorted(set(blockers))
