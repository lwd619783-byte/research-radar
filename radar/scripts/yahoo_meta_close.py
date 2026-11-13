"""Allow a same-session Yahoo chart snapshot to supply a missing raw close."""
import datetime as dt
import re
from zoneinfo import ZoneInfo

from integrity import number, valid_bars
from market_calendar import calendar_data, context, is_session, session_close

SOURCE = 'yahoo-meta-close'
PROOF_KEYS = {'date', 'price', 'marketTime', 'sessionClose', 'nextSessionOpen', 'receivedAt'}
CONFIRMED = ('official', 'rule_based')
MAX_SAFE_INTEGER = (1 << 53) - 1
RECEIPT = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)')


def epoch(value):
    return type(value) is int and 0 < value <= MAX_SAFE_INTEGER


def public_number(value):
    if type(value) is int and abs(value) <= MAX_SAFE_INTEGER:
        return value
    if type(value) is float and number(value) and abs(value) <= MAX_SAFE_INTEGER:
        return value
    return None


def positive_price(value):
    safe = public_number(value)
    return safe is not None and safe > 0


def chart_evidence(payload, symbol, received_at):
    """Extract public close evidence even when the normal parser has no bars."""
    chart = payload.get('chart') if isinstance(payload, dict) else None
    results = chart.get('result') if isinstance(chart, dict) else None
    item = results[0] if isinstance(results, list) and results else None
    meta = item.get('meta') if isinstance(item, dict) else None
    if not isinstance(meta, dict) or meta.get('symbol') != symbol:
        return None
    try:
        zone = ZoneInfo(meta.get('exchangeTimezoneName'))
    except (KeyError, TypeError, ValueError):
        return None
    timestamps = item.get('timestamp')
    indicators = item.get('indicators')
    quotes = indicators.get('quote') if isinstance(indicators, dict) else None
    quote = quotes[0] if isinstance(quotes, list) and quotes and isinstance(quotes[0], dict) else {}
    closes = quote.get('close')
    chart_shape_valid = ((timestamps is None or isinstance(timestamps, list))
                         and (closes is None or isinstance(closes, list))
                         and (not timestamps or bool(quote)))
    closes = closes if isinstance(closes, list) else []
    rows = []
    if isinstance(timestamps, list):
        for i in range(max(0, len(timestamps) - 3), len(timestamps)):
            stamp = timestamps[i]
            if not epoch(stamp):
                chart_shape_valid = False
                continue
            try:
                day = dt.datetime.fromtimestamp(stamp, zone).date().isoformat()
            except (ValueError, OverflowError, OSError):
                chart_shape_valid = False
                continue
            value = closes[i] if i < len(closes) else None
            status = ('close_missing' if i >= len(closes) else 'null' if value is None
                      else 'positive' if positive_price(value) else 'invalid')
            rows.append({'date': day, 'timestamp': stamp, 'close': public_number(value), 'closeStatus': status})
    trading = meta.get('currentTradingPeriod')
    periods = {}
    if isinstance(trading, dict):
        for name in ('pre', 'regular', 'post'):
            part = trading.get(name)
            if isinstance(part, dict) and epoch(part.get('start')) and epoch(part.get('end')):
                offset = part.get('gmtoffset')
                periods[name] = {'start': part['start'], 'end': part['end']}
                if type(offset) is int and abs(offset) <= 24 * 3600:
                    periods[name]['gmtoffset'] = offset
    market_time = meta.get('regularMarketTime')
    return {'lastThree': rows, 'regularMarketPrice': public_number(meta.get('regularMarketPrice')),
            'regularMarketTime': market_time if epoch(market_time) else None,
            'currentTradingPeriod': periods, 'receivedAt': received_at,
            'currency': meta.get('currency'), 'timezone': meta.get('exchangeTimezoneName'),
            'chartShapeValid': chart_shape_valid}


def session_window(symbol, day, now):
    """Use the reviewed current date and the next reviewed trading open."""
    cal = context(symbol, now)
    if cal['confidence'] not in CONFIRMED or cal['expectedCompletedDate'] != day or not day:
        return None
    if cal['exchange'] == 'XTAI':
        return None  # This route cannot satisfy Taiwan's existing independent close proof.
    spec = calendar_data()['exchanges'][cal['exchange']]
    trading_day = dt.date.fromisoformat(day)
    if spec['confidenceByYear'].get(str(trading_day.year)) not in CONFIRMED or not is_session(spec, trading_day):
        return None
    for offset in range(1, 33):
        next_day = trading_day + dt.timedelta(days=offset)
        if (next_day.isoformat() > spec['validThrough']
                or spec['confidenceByYear'].get(str(next_day.year)) not in CONFIRMED):
            break
        if is_session(spec, next_day):
            opening = dt.datetime.combine(next_day, dt.time.fromisoformat(spec['open']), ZoneInfo(spec['timezone']))
            return int(session_close(spec, trading_day).timestamp()), int(opening.timestamp()), cal['timezone']
    return None


def valid_proof(proof, symbol, now):
    if (not isinstance(proof, dict) or set(proof) != PROOF_KEYS or not positive_price(proof.get('price'))
            or not all(epoch(proof.get(key)) for key in ('marketTime', 'sessionClose', 'nextSessionOpen'))):
        return False
    received_at = proof.get('receivedAt')
    if not isinstance(received_at, str) or not RECEIPT.fullmatch(received_at):
        return False
    if not received_at.endswith('Z') and (int(received_at[-5:-3]) > 23 or int(received_at[-2:]) > 59):
        return False
    try:
        received = dt.datetime.fromisoformat(received_at)
        window = session_window(symbol, proof['date'], now)
        return bool(window and window[:2] == (proof['sessionClose'], proof['nextSessionOpen'])
                    and proof['sessionClose'] <= proof['marketTime'] < proof['nextSessionOpen']
                    and proof['marketTime'] <= received.timestamp() and received <= now)
    except (TypeError, ValueError, OverflowError, OSError):
        return False


def missing_close(record, evidence, symbol, now):
    """Identify a missing expected close even when a newer intraday row exists."""
    if not evidence:
        return False
    cal = context(symbol, now)
    day = cal['expectedCompletedDate']
    bars = (record or {}).get('bars') or []
    if cal['confidence'] not in CONFIRMED or not day or any(bar[0] == day for bar in bars):
        return False
    rows = evidence['lastThree']
    target = [row for row in rows if row['date'] == day]
    if target:
        return all(row['closeStatus'] in ('null', 'close_missing') for row in target)
    return not rows or (rows[0]['date'] < day and all(row['date'] <= cal['localDate'] for row in rows))


def supplement(record, evidence, company, now):
    symbol = company['sym']
    if not record or not missing_close(record, evidence, symbol, now):
        return record
    cal = context(symbol, now)
    day = cal['expectedCompletedDate']
    window = session_window(symbol, day, now)
    bars = record.get('bars')
    if (not window or not valid_bars(bars) or record.get('src') != 'yahoo' or record.get('schemaVersion') != 2
            or record.get('priceBasis') != 'raw' or record.get('currency') != company['cur']
            or record.get('timezone') != window[2] or record.get('asOf') != bars[-1][0]):
        return record
    if record['asOf'] > day:
        from snapshot import completed_bars
        completed = completed_bars(record, symbol=symbol, now=now)
        if (record['asOf'] != cal['localDate'] or record.get('phase') not in ('intraday', 'preopen')
                or not completed or completed[-1][0] > day):
            return record
        bars = completed
    proof = {'date': day, 'price': evidence['regularMarketPrice'], 'marketTime': evidence['regularMarketTime'],
             'sessionClose': window[0], 'nextSessionOpen': window[1], 'receivedAt': evidence['receivedAt']}
    if not valid_proof(proof, symbol, now):
        return record
    # The quote supplies only the raw close. An adjusted close or session high
    # must still come from the daily chart, never from the snapshot price.
    return {**record, 'src': SOURCE, 'asOf': day, 'phase': 'closed', 'receivedAt': proof['receivedAt'],
            'bars': [*bars, [day, proof['price'], None, None]], 'yahooMetaClose': proof}
