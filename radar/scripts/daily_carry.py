"""Select a company close from a verified release when its current close is missing."""

import copy
import datetime as dt
import re
from zoneinfo import ZoneInfo

from equity_close_proof import valid_proof as valid_independent_proof
from integrity import fresh_record, number, valid_bars
import market_calendar as calendar
import reviewed_closures
from snapshot import completed_bars, equity_bar_preopen
import yahoo_meta_close


CARRY_SELECTION_METHOD = 'carried-from-verified-release'
SOURCE = 'verified-release-carry'
ROW_MISSING = 'provider_daily_row_missing'
CLOSE_NULL = 'provider_daily_close_null'
REQUEST_FAILED = 'provider_daily_request_failed'
REASONS = (ROW_MISSING, CLOSE_NULL, REQUEST_FAILED)
DAILY_METRIC_FIELDS = ('price', 'r1d', 'r5', 'r20', 'r60', 'ytd', 'dd52', 'hi52', 's0', 'sd', 'sc', 'ld', 'history')
CONFIRMED_CALENDARS = ('official', 'rule_based')
QUOTE_SELECTION = {'useQuote': False, 'reason': 'carried_daily_quote_order_unproven',
                   'completedBoundaryUTC': None, 'boundaryKind': None}


def _iso_date(value):
    return isinstance(value, str) and dt.date.fromisoformat(value).isoformat() == value


def previous_completed_date(symbol, now):
    """Return the exchange session immediately preceding the expected close."""
    context = calendar.context(symbol, now)
    day = context['expectedCompletedDate']
    if not day or context['confidence'] not in CONFIRMED_CALENDARS:
        return None
    spec = calendar.calendar_data()['exchanges'][context['exchange']]
    expected = dt.date.fromisoformat(day)
    if (spec['confidenceByYear'].get(str(expected.year)) not in CONFIRMED_CALENDARS
            or not calendar.is_session(spec, expected)):
        return None
    for distance in range(1, 33):
        prior = expected - dt.timedelta(days=distance)
        if (prior.isoformat() < spec['validFrom']
                or spec['confidenceByYear'].get(str(prior.year)) not in CONFIRMED_CALENDARS):
            return None
        if calendar.is_session(spec, prior):
            return prior.isoformat()
    return None


def carry_calendar(symbol, now):
    context = calendar.context(symbol, now)
    expected = context['expectedCompletedDate']
    if not expected or context['confidence'] not in CONFIRMED_CALENDARS:
        return None
    spec = calendar.calendar_data()['exchanges'][context['exchange']]
    if spec['confidenceByYear'].get(expected[:4]) not in CONFIRMED_CALENDARS:
        return None
    return context, spec


def _known_closed(symbol, market, day):
    spec = calendar.calendar_data()['exchanges'][calendar.exchange_for(symbol)]
    date = dt.date.fromisoformat(day)
    return reviewed_closures.known_closed(market, day) or (
        spec['validFrom'] <= day <= spec['validThrough']
        and spec['confidenceByYear'].get(str(date.year)) in CONFIRMED_CALENDARS
        and not calendar.is_session(spec, date))


def _transport_outcome(value):
    if isinstance(value, dict):
        failure = value.get('failure')
        statuses = [item.get('httpStatus') for item in (value.get('requests') or ()) if isinstance(item, dict)]
        return failure, statuses
    return value, []


def _request_failure(failure, statuses):
    if failure in ('transport_error_no_retry', 'source_transport_failed', 'TimeoutError', 'ConnectionError'):
        return True
    if failure != 'http_error_no_more_retries':
        return False
    return bool(statuses) and all(type(status) is int and (status in (404, 410, 429) or 500 <= status < 600)
                                  for status in statuses)


def _daily_conflicts(company, record, context, now):
    symbol, market = company['sym'], company['mkt']
    bars = record.get('bars')
    day = record.get('asOf')
    if (record.get('schemaVersion') != 2 or record.get('src') not in ('yahoo', yahoo_meta_close.SOURCE)
            or record.get('priceBasis') != 'raw' or record.get('currency') != company['cur']
            or record.get('timezone') != context['timezone'] or not valid_bars(bars)
            or day != bars[-1][0] or not fresh_record(record, now) or 'providerCloseConflict' in record
            or any(not _iso_date(bar[0]) or bar[0] > context['localDate'] or _known_closed(symbol, market, bar[0])
                   for bar in bars)):
        return True
    if any(bar[0] == context['expectedCompletedDate'] for bar in bars):
        return True  # The expected date was present but did not pass selection.

    phase = record.get('phase')
    received = dt.datetime.fromisoformat(record['receivedAt'])
    if 'independentCloseProof' in record and not valid_independent_proof(
            record, record['independentCloseProof'], symbol=symbol, day=day, now=now):
        return True
    if (record['src'] == yahoo_meta_close.SOURCE or 'yahooMetaClose' in record) and (
            record['src'] != yahoo_meta_close.SOURCE or not yahoo_meta_close.valid_proof(
                record.get('yahooMetaClose'), symbol, now)):
        return True
    if phase == 'closed':
        spec = calendar.calendar_data()['exchanges'][context['exchange']]
        complete = completed_bars(record, symbol=symbol, now=now)
        if not complete or complete[-1][0] != day or received < calendar.session_close(spec, dt.date.fromisoformat(day)):
            return True
    elif phase in ('intraday', 'preopen'):
        finality = record.get('finality') or {}
        start, end = finality.get('start'), finality.get('end')
        stamp = (record.get('barTimestamps') or {}).get(day)
        if (day != context['localDate'] or day <= context['expectedCompletedDate']
                or finality.get('method') != 'provider-session-boundary'
                or not all(number(value) and value > 0 for value in (stamp, start, end))):
            return True
        if phase == 'preopen':
            return not equity_bar_preopen(day, stamp, record['timezone'], finality, record['receivedAt'])
        zone = ZoneInfo(record['timezone'])
        return not (0 < end - start <= 26 * 3600 and start <= stamp <= received.timestamp() < end
                    and all(dt.datetime.fromtimestamp(value, zone).date().isoformat() == day
                            for value in (start, stamp, end)))
    else:
        return True
    return False


def _chart_reason(company, record, evidence, context, now):
    expected = context['expectedCompletedDate']
    rows = evidence.get('lastThree')
    if not isinstance(rows, list) or len(rows) > 3 or evidence.get('chartShapeValid') is False:
        return None
    if (evidence.get('currency', (record or {}).get('currency')) != company['cur']
            or evidence.get('timezone', (record or {}).get('timezone')) != context['timezone']):
        return None
    received = dt.datetime.fromisoformat(evidence['receivedAt'])
    if received.tzinfo is None or not dt.timedelta() <= now - received <= dt.timedelta(hours=36):
        return None
    if record is not None and received > dt.datetime.fromisoformat(record['receivedAt']):
        return None  # Chart and parsed series must come from the same observation.

    previous = ''
    target = None
    zone = ZoneInfo(context['timezone'])
    for row in rows:
        day, stamp, state = row['date'], row['timestamp'], row['closeStatus']
        if (not _iso_date(day) or day <= previous or day > context['localDate']
                or type(stamp) is not int or not 0 < stamp <= received.timestamp()
                or dt.datetime.fromtimestamp(stamp, zone).date().isoformat() != day
                or state not in ('positive', 'null', 'close_missing')
                or _known_closed(company['sym'], company['mkt'], day)):
            return None
        close = row.get('close')
        if state == 'positive':
            if not number(close) or close <= 0 or record is None:
                return None
            parsed = next((bar for bar in record['bars'] if bar[0] == day), None)
            if parsed is None or parsed[1] != close or record.get('barTimestamps', {}).get(day) != stamp:
                return None
        elif 'close' not in row or close is not None:
            return None
        if day == expected:
            target = state
        previous = day
    if target == 'null':
        return CLOSE_NULL
    if target == 'close_missing' or target is None and (not rows or rows[0]['date'] < expected):
        return ROW_MISSING
    return None


def classify_missing(company, record, evidence, transport_failure, now):
    """Allow carry only for explicitly observed absence or an unambiguous transport failure."""
    try:
        reviewed = carry_calendar(company['sym'], now)
        if not reviewed:
            return None
        context, _ = reviewed
        failure, statuses = _transport_outcome(transport_failure)
        if failure == 'access_refused_stop_path' or any(status in (401, 403, 451) for status in statuses):
            return None
        if record is not None and (not isinstance(record, dict) or _daily_conflicts(company, record, context, now)):
            return None
        if isinstance(evidence, dict):
            return _chart_reason(company, record, evidence, context, now)
        if record is None and _request_failure(failure, statuses):
            return REQUEST_FAILED
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, OSError):
        return None
    return None


def select_carry(company, baseline_row, baseline_production_sha, baseline_run_id, reason, now):
    """Copy only the dated close and its metrics from an already verified baseline row."""
    try:
        if (not isinstance(baseline_row, dict) or reason not in REASONS
                or not isinstance(baseline_production_sha, str) or not re.fullmatch(r'[0-9a-f]{40}', baseline_production_sha)
                or not isinstance(baseline_run_id, str) or not re.fullmatch(r'[1-9][0-9]*', baseline_run_id)
                or any(baseline_row.get(key) != company[key] for key in ('sym', 'mkt', 'cur'))):
            return None
        symbol = company['sym']
        reviewed = carry_calendar(symbol, now)
        if not reviewed:
            return None
        context, spec = reviewed
        day = baseline_row.get('ld')
        if (not _iso_date(day)
                or day not in (context['expectedCompletedDate'], previous_completed_date(symbol, now))
                or _known_closed(symbol, company['mkt'], day)):
            return None

        old_daily = baseline_row['provenance']['daily']
        source = old_daily['src']
        price = baseline_row['price']
        if (not number(price) or price <= 0 or not source or old_daily.get('phase') != 'closed'
                or old_daily.get('asOf') != day or old_daily.get('timezone') != context['timezone']
                or baseline_row.get('metricAsOf') != day or baseline_row.get('priceAsOf') != day
                or baseline_row.get('pricePhase') != 'closed' or baseline_row.get('priceSource') != source
                or 'priceObservedAt' not in baseline_row or baseline_row['priceObservedAt'] is not None
                or baseline_row.get('stale')):
            return None
        received = dt.datetime.fromisoformat(old_daily['receivedAt'])
        original_close = calendar.session_close(spec, dt.date.fromisoformat(day))
        if received.tzinfo is None or not original_close <= received <= now:
            return None
        prior_marker = baseline_row.get('carried')
        if 'carried' in baseline_row and (not isinstance(prior_marker, dict)
                or prior_marker.get('date') != day or prior_marker.get('carriedSince') != day
                or source != SOURCE or old_daily.get('snapshotSelection', {}).get('method') != CARRY_SELECTION_METHOD):
            return None
        if source == SOURCE and not prior_marker:
            return None
        original_source = old_daily.get('carriedSource') if prior_marker else source
        if not isinstance(original_source, str) or not original_source or original_source == SOURCE:
            return None

        metrics = {key: copy.deepcopy(baseline_row[key]) for key in DAILY_METRIC_FIELDS}
        provenance = {key: old_daily[key] for key in ('asOf', 'receivedAt', 'returnBasis', 'phase', 'timezone')}
        provenance.update(src=SOURCE, carriedSource=original_source)
        provenance['snapshotSelection'] = {'method': CARRY_SELECTION_METHOD, 'selectedDate': day,
                                          'sourceAsOf': day, 'sourcePhase': 'closed'}
        marker = {'date': day, 'carriedSince': day, 'baselineProductionSHA': baseline_production_sha,
                  'baselineRunId': baseline_run_id, 'reason': reason}
        return metrics, provenance, marker
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return None
