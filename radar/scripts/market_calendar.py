"""Reviewed exchange sessions, never a substitute for provider close evidence.

Explicit provisional holidays require an estimate label and an exact date match.
The static export avoids a pandas/calendar dependency in the production runtime.
"""
import datetime as dt
from functools import lru_cache
import json
from pathlib import Path
from zoneinfo import ZoneInfo


@lru_cache(maxsize=1)
def calendar_data():
    return json.loads((Path(__file__).resolve().parents[1] / 'data/market_calendar.json').read_text('utf-8'))


def exchange_for(symbol):
    if not isinstance(symbol, str):
        return None
    known = calendar_data()['symbolExchanges'].get(symbol)
    if known:
        return known
    for suffix, exchange in (('.SS', 'XSHG'), ('.SZ', 'XSHE'), ('.HK', 'XHKG'),
                             ('.TW', 'XTAI'), ('.KS', 'XKRX'), ('.T', 'XTKS'),
                             ('.DE', 'XETR'), ('.PA', 'XPAR')):
        if symbol.endswith(suffix):
            return exchange
    return None


def _confirmed(spec, day):
    return spec['confidenceByYear'].get(str(day.year)) in ('official', 'rule_based')


def _holidays(spec, day):
    confidence = spec['confidenceByYear'].get(str(day.year))
    if confidence in ('official', 'rule_based'):
        return spec['holidays']
    if confidence == 'provisional':
        return spec.get('provisionalHolidays', [])
    return []


def is_session(spec, day):
    return day.weekday() < 5 and day.isoformat() not in _holidays(spec, day)


def known_non_session(symbol, day):
    """Can a provider tail row be excluded on confirmed calendar evidence?

    An estimated weekday holiday cannot override an observed provider row.
    Weekends use the existing exchange trading week within reviewed coverage.
    """
    exchange = exchange_for(symbol)
    if not exchange:
        return False
    spec = calendar_data()['exchanges'][exchange]
    try:
        date = dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        return False
    if not spec['validFrom'] <= day <= spec['validThrough']:
        return False
    return date.weekday() >= 5 or (spec['confidenceByYear'].get(str(date.year)) == 'official'
                                   and day in spec['holidays'])


def session_close(spec, day):
    close = spec['earlyCloses'].get(day.isoformat(), spec['close']) if _confirmed(spec, day) else spec['close']
    return dt.datetime.combine(day, dt.time.fromisoformat(close), ZoneInfo(spec['timezone']))


def context(symbol, now):
    exchange = exchange_for(symbol)
    base = {'exchange': exchange, 'timezone': None, 'expectedCompletedDate': None,
            'confidence': 'unavailable', 'validThrough': calendar_data()['validThrough'],
            'warnings': [], 'holidayGap': False, 'sessionToday': False, 'localDate': None}
    if not exchange or now.tzinfo is None:
        return {**base, 'warnings': ['交易所日历未配置，不能确认行情新鲜度']}
    spec = calendar_data()['exchanges'][exchange]
    local = now.astimezone(ZoneInfo(spec['timezone']))
    today = local.date()
    confidence = spec['confidenceByYear'].get(str(today.year), 'unavailable')
    base.update(timezone=spec['timezone'], localDate=today.isoformat(), confidence=confidence,
                sessionToday=is_session(spec, today), sources=spec['sources'])
    remaining = (dt.date.fromisoformat(spec['validThrough']) - today).days
    if remaining <= calendar_data()['warningDays']:
        base['warnings'].append(f'{exchange} 交易日历将于 {spec["validThrough"]} 到期，请核实下一年度安排' if remaining >= 0 else f'{exchange} 交易日历已到期，禁止沿用未核实安排')
    pending_years = [year for year, value in spec['confidenceByYear'].items() if value in ('unconfirmed', 'provisional')]
    for year in pending_years:
        boundary = dt.date(int(year), 1, 1)
        if today.year == int(year) or 0 <= (boundary - today).days <= calendar_data()['warningDays']:
            base['warnings'].append(f'{exchange} {year} 年交易安排待官方确认；{spec.get("provisionalNote", "请补充官方安排") }')
    if not spec['validFrom'] <= today.isoformat() <= spec['validThrough']:
        return {**base, 'confidence': 'unavailable'}
    candidate = today
    # Bounded lookback also fails closed when the reviewed table has expired.
    for _ in range(32):
        if candidate.isoformat() < spec['validFrom']:
            break
        if is_session(spec, candidate) and now >= session_close(spec, candidate):
            base['expectedCompletedDate'] = candidate.isoformat()
            break
        if candidate.weekday() < 5 and candidate.isoformat() in _holidays(spec, candidate):
            base['holidayGap'] = True
        candidate -= dt.timedelta(days=1)
    return base


def date_is_fresh(symbol, day, now, *, allow_intraday=False, phase='closed'):
    ctx = context(symbol, now)
    if ctx['confidence'] == 'unavailable' or not ctx['expectedCompletedDate']:
        return False
    if day == ctx['expectedCompletedDate']:
        return True
    # Calendar knowledge cannot promote today's unfinished/unknown bar to closed.
    return bool(allow_intraday and phase in ('intraday', 'unknown') and ctx['sessionToday']
                and day == ctx['localDate'] and day > ctx['expectedCompletedDate'])


def annotate(symbol, day, now, *, completed=False):
    ctx = context(symbol, now)
    matches = bool(day and day == ctx['expectedCompletedDate'])
    carry = bool(matches and completed and ctx['holidayGap'] and ctx['confidence'] in ('official', 'rule_based', 'provisional'))
    status = 'holiday_carry' if carry else 'current' if matches else 'stale'
    if ctx['confidence'] in ('unconfirmed', 'unavailable'):
        status = 'unconfirmed'
    return {key: value for key, value in {**ctx, 'status': status, 'quoteDate': day,
            'label': (f'休市·沿用 {day[5:7]}/{day[8:10]} 收盘' + ('（待官方确认）' if ctx['confidence'] == 'provisional' else '')) if carry else None}.items()
            if key not in ('holidayGap', 'sessionToday', 'localDate')}


def metadata(symbols, now):
    exchanges = {}
    for symbol in symbols:
        item = context(symbol, now)
        exchanges[item['exchange'] or 'unknown'] = item
    return {'validThrough': calendar_data()['validThrough'], 'warningDays': calendar_data()['warningDays'],
            'warnings': sorted({w for item in exchanges.values() for w in item['warnings']}),
            'exchanges': exchanges}
