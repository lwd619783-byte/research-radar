"""Narrow, same-execution TWSE terminal-close evidence for 2383.TW only.

The original Yahoo observations and provider finality rules stay unchanged.
HTTPS provenance is established by the bounded collector, not by a checksum.
The checksum binds the safe evidence summary; it is not an origin signature.
No network access, raw response export, cache admission or publication occurs here.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
import re
from zoneinfo import ZoneInfo

import market_calendar
from integrity import valid_bars

SYMBOL = '2383.TW'
METHOD = 'twse-independent-close'
PROOF_KEY = 'independentCloseProof'
YAHOO_URL = ('https://query1.finance.yahoo.com/v8/finance/chart/2383.TW'
             '?range=5y&interval=1d&includeAdjustedClose=true')
EXECUTION_KEYS = ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')
FIELDS = ('日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價',
          '收盤價', '漲跌價差', '成交筆數', '註記')
SUMMARY_KEYS = frozenset(('schemaVersion', 'method', 'symbol', 'exchange', 'currency',
    'day', 'timezone', 'sourcePhase', 'officialSourceUrl', 'yahooSourceUrl',
    'officialResponseSHA256', 'yahooResponseSHA256', 'yahooRecordSHA256',
    'officialReceivedAt', 'yahooReceivedAt', 'parserReceivedAt', 'checkedAt',
    'execution', 'officialResponseDate', 'officialTitle', 'officialRow',
    'close', 'adjclose', 'high', 'barTimestamp', 'sessionStart', 'sessionEnd', 'checksum'))
ZONE = ZoneInfo('Asia/Taipei')
HASH = re.compile(r'[0-9a-f]{64}')
PRICE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?')


def official_url(day):
    """The exact allowlisted request, not an arbitrary supplied URL."""
    parsed = dt.date.fromisoformat(day)
    if parsed.isoformat() != day:
        raise ValueError('invalid_day')
    return ('https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY'
            f'?date={day.replace("-", "")}&stockNo=2383&response=json')


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def record_digest(record):
    """Bind every original parsed field, excluding only the additive proof."""
    if not isinstance(record, dict):
        raise ValueError('invalid_record')
    return _digest({key: value for key, value in record.items() if key != PROOF_KEY})


def current_execution():
    """Read only public GitHub identity keys; never copy the environment."""
    return {key: os.environ.get(key, '') for key in EXECUTION_KEYS}


def _identity(execution):
    if not isinstance(execution, dict):
        raise ValueError('invalid_execution')
    value = {key: execution.get(key) for key in EXECUTION_KEYS}
    if (not isinstance(value['GITHUB_SHA'], str)
            or re.fullmatch(r'[0-9a-f]{40}', value['GITHUB_SHA']) is None
            or not isinstance(value['GITHUB_RUN_ID'], str)
            or re.fullmatch(r'[1-9][0-9]*', value['GITHUB_RUN_ID']) is None
            or value['GITHUB_RUN_ATTEMPT'] != '1'):
        raise ValueError('invalid_execution')
    return value


def _aware(value):
    if not isinstance(value, str):
        raise ValueError('invalid_time')
    parsed = dt.datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError('naive_time')
    return parsed


def _decimal(value, *, formatted=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid_price')
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('invalid_price')
    text = str(value)
    if formatted:
        if re.fullmatch(r'(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|0|[1-9][0-9]*)(?:\.[0-9]+)?', text) is None:
            raise ValueError('invalid_price')
        text = text.replace(',', '')
    elif PRICE.fullmatch(text) is None:
        raise ValueError('invalid_price')
    number = Decimal(text)
    if not number.is_finite() or number <= 0:
        raise ValueError('invalid_price')
    normalized = format(number, 'f')
    return normalized.rstrip('0').rstrip('.') if '.' in normalized else normalized


def _integer(value):
    if type(value) is not int or value <= 0 or value > 2**53 - 1:
        raise ValueError('invalid_timestamp')
    return value


def _expected(day, now):
    if not isinstance(now, dt.datetime) or now.utcoffset() is None:
        raise ValueError('invalid_clock')
    date = dt.date.fromisoformat(day)
    if date.isoformat() != day:
        raise ValueError('invalid_day')
    ctx = market_calendar.context(SYMBOL, now)
    if (ctx.get('exchange') != 'XTAI' or ctx.get('timezone') != 'Asia/Taipei'
            or ctx.get('confidence') != 'official' or ctx.get('expectedCompletedDate') != day
            or market_calendar.known_non_session(SYMBOL, day)):
        raise ValueError('unconfirmed_calendar')
    spec = market_calendar.calendar_data()['exchanges']['XTAI']
    close = market_calendar.session_close(spec, date)
    # This first implementation admits only the reviewed normal 13:30 session.
    if close.time() != dt.time(13, 30) or now < close or now.astimezone(ZONE).date() != date:
        raise ValueError('unsupported_session')
    return close


def _title(title, day):
    if not isinstance(title, str) or len(title) > 160:
        raise ValueError('invalid_title')
    match = re.fullmatch(r'([0-9]{2,3})年([0-9]{1,2})月2383台光電各日成交資訊', re.sub(r'\s', '', title))
    date = dt.date.fromisoformat(day)
    if match is None or int(match[1]) != date.year - 1911 or int(match[2]) != date.month:
        raise ValueError('invalid_title')
    return title


def _roc(day):
    date = dt.date.fromisoformat(day)
    return f'{date.year - 1911}/{date.month:02}/{date.day:02}'


def _official_row(document, day):
    if (not isinstance(document, dict) or document.get('stat') != 'OK'
            or document.get('date') != day.replace('-', '')
            or not isinstance(document.get('fields'), list)
            or len(document['fields']) != len(FIELDS) or set(document['fields']) != set(FIELDS)
            or not isinstance(document.get('data'), list) or not document['data']
            or len(document['data']) > 32):
        raise ValueError('invalid_official_document')
    _title(document.get('title'), day)
    selected, seen = None, set()
    wanted = dt.date.fromisoformat(day)
    for values in document['data']:
        if not isinstance(values, list) or len(values) != len(FIELDS):
            raise ValueError('invalid_official_row')
        row = dict(zip(document['fields'], values))
        match = re.fullmatch(r'([0-9]{2,3})/([0-9]{2})/([0-9]{2})', row.get('日期', ''))
        if match is None:
            raise ValueError('invalid_official_date')
        date = dt.date(int(match[1])+1911, int(match[2]), int(match[3]))
        if date in seen or date.year != wanted.year or date.month != wanted.month or date > wanted:
            raise ValueError('ambiguous_official_date')
        seen.add(date)
        if date == wanted:
            if row.get('註記') != '':
                raise ValueError('unreviewed_corporate_action_note')
            selected = {'date': _roc(day), 'close': _decimal(row['收盤價'], formatted=True),
                        'high': _decimal(row['最高價'], formatted=True), 'note': ''}
    if selected is None or Decimal(selected['high']) < Decimal(selected['close']):
        raise ValueError('official_row_missing_or_invalid')
    return selected


def _record_fields(record, day, now):
    if (not isinstance(record, dict) or record.get('schemaVersion') != 2
            or record.get('src') != 'yahoo' or record.get('priceBasis') != 'raw'
            or record.get('returnBasis') != 'yahoo-adjclose' or record.get('currency') != 'TWD'
            or record.get('timezone') != 'Asia/Taipei' or record.get('phase') != 'unknown'
            or record.get('asOf') != day or not valid_bars(record.get('bars'))
            or record['bars'][-1][0] != day):
        raise ValueError('invalid_yahoo_record')
    session = record.get('finality')
    stamps = record.get('barTimestamps')
    if (not isinstance(session, dict) or session.get('method') != 'provider-session-boundary'
            or not isinstance(stamps, dict)):
        raise ValueError('provider_metadata_missing')
    close = _expected(day, now)
    start, end, timestamp = map(_integer, (session.get('start'), session.get('end'), stamps.get(day)))
    if (not 0 < end-start <= 12*3600 or end < close.timestamp() or not end < timestamp
            or any(dt.datetime.fromtimestamp(value, ZONE).date().isoformat() != day
                   for value in (start, end, timestamp))):
        raise ValueError('not_supported_post_session_observation')
    receipt = _aware(record.get('receivedAt'))
    if not close <= receipt <= now or not 0 <= (now-receipt).total_seconds() <= 36*3600:
        raise ValueError('invalid_receipt')
    if timestamp > receipt.timestamp():
        raise ValueError('future_observation')
    row = record['bars'][-1]
    prices = tuple(_decimal(value) for value in row[1:4])
    if prices[0] != prices[1] or Decimal(prices[2]) < Decimal(prices[0]):
        raise ValueError('terminal_adjustment_not_proven')
    return {'close': prices[0], 'adjclose': prices[1], 'high': prices[2],
            'barTimestamp': timestamp, 'sessionStart': start, 'sessionEnd': end,
            'parserReceivedAt': record['receivedAt']}


def _event(event, source, now, close):
    if (not isinstance(event, dict) or event.get('sourceUrl') != source
            or type(event.get('httpStatus')) is not int or event['httpStatus'] != 200
            or not isinstance(event.get('sha256'), str) or HASH.fullmatch(event['sha256']) is None):
        raise ValueError('invalid_transport_evidence')
    receipt = _aware(event.get('receivedAt'))
    if not close <= receipt <= now or not 0 <= (now-receipt).total_seconds() <= 36*3600:
        raise ValueError('invalid_transport_receipt')
    return event['receivedAt']


def make_proof(record, official_document, *, official_event, yahoo_event,
               expected_day, now, execution):
    """Construct evidence only from the collector's same-run HTTPS observations."""
    try:
        close = _expected(expected_day, now)
        fields = _record_fields(record, expected_day, now)
        row = _official_row(official_document, expected_day)
        if row['close'] != fields['close'] or row['high'] != fields['high']:
            return None
        proof = {'schemaVersion': 1, 'method': METHOD, 'symbol': SYMBOL,
            'exchange': 'XTAI', 'currency': 'TWD', 'day': expected_day,
            'timezone': 'Asia/Taipei', 'sourcePhase': 'unknown',
            'officialSourceUrl': official_url(expected_day), 'yahooSourceUrl': YAHOO_URL,
            'officialResponseSHA256': official_event['sha256'],
            'yahooResponseSHA256': yahoo_event['sha256'],
            'yahooRecordSHA256': record_digest(record),
            'officialReceivedAt': _event(official_event, official_url(expected_day), now, close),
            'yahooReceivedAt': _event(yahoo_event, YAHOO_URL, now, close),
            'checkedAt': now.isoformat(), 'execution': _identity(execution),
            'officialResponseDate': official_document['date'],
            'officialTitle': official_document['title'], 'officialRow': row, **fields}
        proof['checksum'] = _digest(proof)
        return proof if valid_summary(proof, now=now, execution=execution) else None
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError, OSError):
        return None


def valid_summary(proof, *, now, execution):
    """Recheck the safe summary offline, including identity and temporal bounds."""
    try:
        if (not isinstance(proof, dict) or set(proof) != SUMMARY_KEYS
                or type(proof['schemaVersion']) is not int or proof['schemaVersion'] != 1
                or proof['method'] != METHOD or proof['symbol'] != SYMBOL
                or proof['exchange'] != 'XTAI' or proof['currency'] != 'TWD'
                or proof['timezone'] != 'Asia/Taipei' or proof['sourcePhase'] != 'unknown'
                or proof['execution'] != _identity(execution)
                or set(proof['execution']) != set(EXECUTION_KEYS)):
            return False
        day = proof['day']
        close = _expected(day, now)
        if (proof['officialSourceUrl'] != official_url(day) or proof['yahooSourceUrl'] != YAHOO_URL
                or proof['officialResponseDate'] != day.replace('-', '')):
            return False
        _title(proof['officialTitle'], day)
        if any(not isinstance(proof[key], str) or HASH.fullmatch(proof[key]) is None
               for key in ('officialResponseSHA256', 'yahooResponseSHA256', 'yahooRecordSHA256', 'checksum')):
            return False
        if _digest({key: value for key, value in proof.items() if key != 'checksum'}) != proof['checksum']:
            return False
        row = proof['officialRow']
        if (not isinstance(row, dict) or set(row) != {'date', 'close', 'high', 'note'}
                or row['date'] != _roc(day) or row['note'] != ''):
            return False
        for value in (proof['close'], proof['adjclose'], proof['high'], row['close'], row['high']):
            if not isinstance(value, str) or _decimal(value) != value:
                return False
        if (not proof['close'] == proof['adjclose'] == row['close']
                or proof['high'] != row['high'] or Decimal(proof['high']) < Decimal(proof['close'])):
            return False
        checked, official, yahoo, parser = map(_aware, (proof['checkedAt'], proof['officialReceivedAt'],
            proof['yahooReceivedAt'], proof['parserReceivedAt']))
        if (not close <= official <= checked <= now or not close <= yahoo <= parser <= checked
                or any(not 0 <= (now-value).total_seconds() <= 36*3600
                       for value in (checked, official, yahoo, parser))):
            return False
        start, end, stamp = map(_integer, (proof['sessionStart'], proof['sessionEnd'], proof['barTimestamp']))
        return bool(0 < end-start <= 12*3600 and close.timestamp() <= end < stamp <= yahoo.timestamp()
                    and all(dt.datetime.fromtimestamp(value, ZONE).date().isoformat() == day
                            for value in (start, end, stamp)))
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError, OSError):
        return False


def valid_proof(record, proof, *, symbol, day, now, execution=None):
    """A valid summary must match this exact original Yahoo record and run."""
    try:
        if symbol != SYMBOL or proof.get('day') != day:
            return False
        identity = current_execution() if execution is None else execution
        if not valid_summary(proof, now=now, execution=identity):
            return False
        fields = _record_fields(record, day, now)
        return (proof['yahooRecordSHA256'] == record_digest(record)
                and all(proof[key] == value for key, value in fields.items()))
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation, OverflowError, OSError):
        return False


def record_bar_final(record, day, *, symbol, now):
    """Keep the original provider proof first; only the narrow alternative is new."""
    from snapshot import equity_bar_final
    if not isinstance(record, dict):
        return False
    stamps = record.get('barTimestamps')
    stamp = stamps.get(day) if isinstance(stamps, dict) else None
    if equity_bar_final(day, stamp, record.get('timezone'), record.get('finality'), record.get('receivedAt')):
        return True
    return valid_proof(record, record.get(PROOF_KEY), symbol=symbol, day=day, now=now)
