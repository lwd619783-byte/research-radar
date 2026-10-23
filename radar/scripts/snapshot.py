"""Pure, offline selection of a common completed daily snapshot.

Observed bars, not a weekday/holiday calendar, define candidate sessions. The
existing receipt/date age limits remain in force. Missing auxiliary observations
never move the selected date or acquire fabricated historical values.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from integrity import ZONES, fresh_record, fx_bar_final, number, observation_time, valid_bars

CLOSED_QUOTE_STATES = ('CLOSED', 'POST', 'POSTPOST', 'PRE', 'PREPRE')


def equity_bar_preopen(day, timestamp, timezone, session, received_at):
    """Classify a same-day pre-open observation, never certify its close.

    Some providers return an auction/current-day bar before the regular session
    begins. Its presence must not discard earlier, independently proven closes.
    Both the latest bar and receipt must precede today's provider session start;
    absent, inconsistent or future metadata remains unknown.
    """
    try:
        if not isinstance(session, dict) or session.get('method') != 'provider-session-boundary':
            return False
        start, end = session['start'], session['end']
        if not all(number(x) and x > 0 for x in (timestamp, start, end)) or not 0 < end-start <= 12*3600:
            return False
        zone = ZoneInfo(timezone)
        received = dt.datetime.fromisoformat(received_at)
        if received.tzinfo is None or not timestamp <= received.timestamp() < start:
            return False
        local_days = [dt.datetime.fromtimestamp(value, zone).date().isoformat()
                      for value in (timestamp, start, end)]
        return all(value == day for value in local_days) and received.astimezone(zone).date().isoformat() == day
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return False


def equity_bar_final(day, timestamp, timezone, session, received_at):
    if fx_bar_final(day, timestamp, timezone, session, received_at):
        return True
    # On weekends/pre-open Yahoo may describe the *next* regular session.
    # For these daytime equity markets an observed prior local day predating
    # that session is completed. Never apply this rule to 24-hour FX sessions,
    # to same-day observations, or by advancing a cached receipt timestamp.
    try:
        if not isinstance(session, dict) or session.get('method') != 'provider-session-boundary':
            return False
        start, end = session['start'], session['end']
        if not all(number(x) and x > 0 for x in (timestamp, start, end)) or not 0 < end-start <= 12*3600:
            return False
        zone = ZoneInfo(timezone)
        received = dt.datetime.fromisoformat(received_at)
        if received.tzinfo is None:
            return False
        local_start, local_end = (dt.datetime.fromtimestamp(x, zone) for x in (start, end))
        return (local_start.date() == local_end.date()
                and timestamp <= received.timestamp() < start
                and dt.datetime.fromtimestamp(timestamp, zone).date().isoformat() == day
                and day < received.astimezone(zone).date().isoformat() <= local_start.date().isoformat())
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return False


def completed_bars(record):
    if (not isinstance(record, dict) or record.get('schemaVersion') != 2
            or record.get('priceBasis') != 'raw' or not valid_bars(record.get('bars'))
            or record.get('asOf') != record['bars'][-1][0]
            or record.get('phase') not in ('closed', 'intraday', 'preopen')):
        return []
    if record['phase'] == 'preopen':
        timestamps = record.get('barTimestamps')
        if not isinstance(timestamps, dict) or not equity_bar_preopen(
                record['asOf'], timestamps.get(record['asOf']), record.get('timezone'),
                record.get('finality'), record.get('receivedAt')):
            return []
    if 'finality' in record:
        timestamps = record.get('barTimestamps') or {}
        if not isinstance(timestamps, dict):
            return []
        return [b for b in record['bars'] if equity_bar_final(
            b[0], timestamps.get(b[0]), record.get('timezone'),
            record.get('finality'), record.get('receivedAt'))]
    # Preserve already-recorded closed legacy series. A legacy intraday or
    # unknown marker is insufficient evidence to trim/relabel it as closed.
    return record['bars'] if record.get('phase') == 'closed' else []


def select_daily(companies, records, now):
    histories, candidates = {}, []
    source_dates = {}
    for c in companies:
        record = records.get(c['sym']) or {}
        if not isinstance(record, dict):
            record = {}
        if record.get('asOf'):
            source_dates.setdefault(c['mkt'], set()).add(record['asOf'])
        bars = completed_bars(record)
        if record.get('currency') not in (None, c['cur']):
            bars = []
        if 'finality' in record:
            try:
                provider, expected = ZoneInfo(record.get('timezone')), ZoneInfo(ZONES[c['mkt']])
                bars = [b for b in bars if dt.datetime.fromisoformat(b[0]).replace(tzinfo=provider).utcoffset()
                        == dt.datetime.fromisoformat(b[0]).replace(tzinfo=expected).utcoffset()]
            except (KeyError, TypeError, ValueError):
                bars = []
        histories[c['sym']] = bars
        # Date age only here: stale receipt provenance remains visible and is
        # blocked by assemble, rather than being silently refreshed by selection.
        local_day = now.astimezone(ZoneInfo(ZONES[c['mkt']])).date()
        days = {b[0] for b in bars if 0 <= (local_day-dt.date.fromisoformat(b[0])).days <= 4}
        if days:
            candidates.append(days)
    common = set.intersection(*candidates) if candidates else set()
    day = max(common) if common else None
    selected = {}
    for c in companies:
        bars = histories[c['sym']]
        if day and any(b[0] == day for b in bars):
            original = records[c['sym']]
            selected[c['sym']] = {**original, 'bars': [b for b in bars if b[0] <= day],
                'asOf': day, 'phase': 'closed',
                'snapshotSelection': {'sourceAsOf': original['asOf'], 'sourcePhase': original.get('phase'),
                    'method': 'observed-completed-bars', 'selectedDate': day}}
    return selected, {'policy': 'latest-common-completed-daily', 'selectedDate': day,
        'status': 'complete' if day and len(selected) == len(companies) else 'incomplete',
        'selectedCompanies': len(selected), 'requiredCompanies': len(companies),
        'sourceAsOfByMarket': {k: sorted(v) for k, v in source_dates.items()}}


def select_quote(record, day, market, currency, now):
    observed = observation_time('quote', record)
    observed_day = observed.astimezone(ZoneInfo(ZONES[market])).date().isoformat() if observed else None
    if not day or observed_day != day:
        return {}, 'quote_date_mismatch_or_missing', observed_day
    if not fresh_record(record, now, day, market):
        return {}, 'quote_stale_or_invalid_receipt', observed_day
    # A current regular-session valuation is not a historical closing valuation.
    # Waiting cannot change the marketState captured with the original payload.
    if record.get('marketState') not in CLOSED_QUOTE_STATES:
        return {}, 'quote_close_unconfirmed', observed_day
    if observed > dt.datetime.fromisoformat(record['receivedAt']):
        return {}, 'quote_observation_after_receipt', observed_day
    if record.get('currency') != currency:
        return {}, 'quote_currency_mismatch', observed_day
    return record, 'available', observed_day


def select_index(record, day, now):
    if not day or not isinstance(record, dict):
        return None
    history = record.get('dailyHistory')
    if history is not None:
        bars = [b for b in completed_bars(history) if b[0] <= day]
        if len(bars) < 2 or bars[-1][0] != day or not fresh_record(history, now, day):
            return None
        return {**record, 'price': bars[-1][1], 'chg': bars[-1][1]/bars[-2][1]-1,
                'date': day, 'phase': 'closed', 'sourceDate': record.get('date')}
    if record.get('date') == day and record.get('phase') == 'closed' and fresh_record(record, now, day):
        return record
    return None
