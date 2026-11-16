"""Same-execution diagnostic archive. No fetching, deployment or source payloads."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from zoneinfo import ZoneInfo

import build
import daily_carry
from latest import PROVIDER_CLOSE_CONFLICT_METHOD
import research_snapshot as snapshots
import yahoo_meta_close

MAX_BUNDLE = 10_000_000  # Decimal 10 MB, including manifest; never truncate.
MAX_RECEIPT = 512 * 1024
PAYLOADS = ('DATA.json', 'index.html', 'receipt.json')
FILES = (*PAYLOADS, 'manifest.json')
SNAPSHOT = 'research-snapshot.json'
CONFLICT_RECEIPT = re.compile(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})'
                              r'(?:\.([0-9]{1,6}))?(Z|[+-][0-9]{2}:[0-9]{2})')
FORBIDDEN_KEYS = {
    'cookie', 'cookies', 'cookiejar', 'setcookie', 'headers', 'requestheaders',
    'responseheaders', 'authorization', 'password', 'passwd', 'credential',
    'credentials', 'token', 'accesstoken', 'refreshtoken', 'idtoken', 'apikey',
    'secret', 'clientsecret', 'crumb', 'raw', 'rawbody', 'rawpayload', 'payload',
    'httpbody', 'responsebody', 'requestbody', 'documents', 'chart', 'quoteresponse',
    'body', 'rawresponse', 'httpresponse', 'authentication', 'apitoken',
    'createdby', 'lasteditedby', 'requestid', 'notiontoken',
}
SECRET_VALUE = re.compile(
    r'(?:ntn_[A-Za-z0-9_-]{12,}|secret_[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}'
    r'|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{12,}'
    r'|https?://[^\s/<>]+:[^\s/<>]+@'
    r'|[?&](?:token|access_token|api_key|apikey|crumb|signature|x-amz-signature)=)', re.I)


class BundleError(ValueError):
    """Fixed diagnostic codes only; never include rejected field values."""


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def atomic_directory_rename(stage, destination):
    """Keep the atomic rename; tolerate short Windows scanner sharing locks."""
    for attempt in range(5):
        if Path(destination).exists() or Path(destination).is_symlink():
            raise BundleError('atomic_destination_exists')
        try:
            os.rename(stage, destination)
            return
        except PermissionError:
            if os.name != 'nt' or attempt == 4:
                raise
            time.sleep(.05 * (attempt + 1))


def data_digest(D):
    return digest(encoded(D))


def check_sensitive(value):
    """Reject instead of deleting fields: the archived D must remain complete."""
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r'[^a-z0-9]', '', str(key).lower())
            if normalized in ('cookieavailable', 'crumbavailable') and not isinstance(child, bool):
                raise BundleError('authentication_flag_must_be_boolean')
            if normalized in FORBIDDEN_KEYS:
                raise BundleError('sensitive_or_raw_field')
            check_sensitive(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            check_sensitive(child)
    elif isinstance(value, str) and SECRET_VALUE.search(value):
        raise BundleError('sensitive_value')


def classification(D):
    if D['meta'].get('diagnosticResearchSource') == 'notion-fixture':
        return 'SAME-EXECUTION MARKET DIAGNOSTIC WITH FIXTURE RESEARCH — NOT PUBLICATION'
    return ('OFFLINE TEST DATA — NOT NEW REAL MARKET DATA' if
            any(D['meta'].get(k) for k in ('fixture', 'offline', 'reviewPreview')) else
            'SAME-EXECUTION DIAGNOSTIC SNAPSHOT — NOT PUBLICATION')


def render_archive(D, blockers):
    check_sensitive(D)
    with tempfile.TemporaryDirectory(prefix='radar-render-') as tmp:
        html = build.render(D, Path(tmp)).read_text('utf-8')
    # Archive-only wrapper. No changes to DATA, chart code or production template.
    html = html.replace('<head>', '<head>\n<meta http-equiv="Content-Security-Policy" '
                        'content="default-src \'none\'; script-src \'unsafe-inline\'; '
                        'style-src \'unsafe-inline\'; img-src data:; font-src data:; '
                        'connect-src \'none\'; base-uri \'none\'; form-action \'none\'">', 1)
    text = classification(D) + ' · 验收归档 · 未发布 · blockers=' + str(len(blockers))
    notice = ('<aside id="acceptance-archive-notice" style="position:fixed;bottom:0;left:0;right:0;'
              'z-index:2147483647;padding:12px;background:#ffdb73;color:#211800;'
              'font:700 14px sans-serif;text-align:center">' + text + '</aside>')
    return html.replace('</body>', notice + '\n</body>').encode()


def embedded_data(html):
    matches = re.findall(r'<script>const DATA=(.*?);</script>', html.decode(), re.S)
    if len(matches) != 1:
        raise BundleError('html_data_slot_mismatch')
    return json.loads(matches[0].replace('<\\/', '</'))


def validate_binding(D, receipt, clock):
    check_sensitive(D)
    check_sensitive(receipt)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise BundleError('fixed_clock_requires_timezone')
    execution = receipt['execution']
    if (not re.fullmatch(r'[0-9a-f]{40}', execution.get('GITHUB_SHA', '')) or
            not re.fullmatch(r'[0-9]+', execution.get('GITHUB_RUN_ID', '')) or
            execution.get('GITHUB_RUN_ATTEMPT') != '1'):
        raise BundleError('execution_identity_invalid')
    gate = receipt['publication']
    if (receipt.get('fixedClock') != clock.isoformat() or
            gate.get('dataSHA256') != data_digest(D) or
            gate.get('asOf') != D['meta']['asOf'] or
            gate.get('snapshot') != D['meta']['snapshot'] or
            gate.get('blockers') != build.release_blockers(D) or
            D['meta']['generatedAt'] != clock.isoformat(timespec='minutes') or
            D['meta']['today'] != clock.date().isoformat()):
        raise BundleError('same_snapshot_binding_mismatch')
    validate_close_proofs(D, receipt.get('independentCloseProofs'), execution, clock)
    validate_provider_close_conflicts(D)
    validate_yahoo_meta_closes(D, clock)
    validate_carried_daily(D, clock)


def _valid_close_conflict_day(value):
    try:
        return isinstance(value, str) and dt.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _close_conflict_receipt_seconds(value):
    match = CONFLICT_RECEIPT.fullmatch(value) if isinstance(value, str) else None
    if not match:
        return None
    whole, fraction, zone = match.groups()
    if zone != 'Z' and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
        return None
    try:
        base = dt.datetime.fromisoformat(whole + zone).timestamp()
    except (ValueError, OverflowError, OSError):
        return None
    return base + (float('0.' + fraction) if fraction else 0)


def validate_carried_daily(data, clock):
    """Bind carry markers, reviewed trading dates and coverage in published DATA."""
    import market_calendar as calendar
    from integrity import number

    def fields(value):
        return value if isinstance(value, dict) else {}

    def fail():
        raise BundleError('carried_daily_binding_mismatch')

    def daily_for(row):
        return fields(fields(row.get('provenance')).get('daily'))

    source = daily_carry.SOURCE
    method = daily_carry.CARRY_SELECTION_METHOD
    reason = 'carried_from_verified_release'
    marker_keys = {'date', 'carriedSince', 'baselineProductionSHA', 'baselineRunId', 'reason'}
    rows = data.get('companies')
    rows = [fields(row) for row in rows] if isinstance(rows, list) else []
    meta = fields(data.get('meta'))
    coverage = meta.get('coverage')
    coverage = [fields(item) for item in coverage] if isinstance(coverage, list) else []
    selected = []
    for row in rows:
        daily = daily_for(row)
        if ('carried' in row or 'carriedSource' in daily or source in (row.get('priceSource'), daily.get('src'))
                or fields(daily.get('snapshotSelection')).get('method') == method
                or fields(row.get('marketCalendar')).get('status') == 'carried_daily'):
            selected.append(row)
    carry_coverage = [item for item in coverage if item.get('reason') == reason or item.get('source') == source]
    covered_metrics = {'price': 'price', 'daily': 'ld', 'r5': 'r5', 'r20': 'r20', 'r60': 'r60', 'ytd': 'ytd', 'high52': 'hi52'}
    limit = len(rows) // 10
    if len(selected) > limit or isinstance(meta.get('blockers'), list) and 'carried_daily_exceeds_limit' in meta['blockers']:
        raise BundleError('carried_daily_exceeds_limit')
    if not selected and 'carriedDaily' not in meta and not carry_coverage:
        return
    summary = fields(meta.get('carriedDaily'))
    snapshot = fields(meta.get('snapshot'))
    if (not selected or not isinstance(clock, dt.datetime) or clock.utcoffset() is None
            or set(summary) != {'companies', 'count', 'limit'} or type(summary['count']) is not int
            or summary['count'] != len(selected) or type(summary['limit']) is not int or summary['limit'] != limit
            or not isinstance(summary['companies'], list) or len(summary['companies']) != len(selected)
            or snapshot.get('status') != 'complete'
            or any(type(snapshot.get(key)) is not int or snapshot[key] != len(rows)
                   for key in ('requiredCompanies', 'selectedCompanies'))):
        fail()

    markers = {}
    carried_companies = {}
    baseline = None
    for row in selected:
        symbol = row.get('sym')
        daily = daily_for(row)
        marker = fields(row.get('carried'))
        annotation = fields(row.get('marketCalendar'))
        selection = fields(daily.get('snapshotSelection'))
        quote = fields(row.get('priceSelection'))
        day, sha, run = (marker.get(key) for key in ('date', 'baselineProductionSHA', 'baselineRunId'))
        if (not isinstance(symbol, str) or not symbol or sum(item.get('sym') == symbol for item in rows) != 1
                or set(marker) != marker_keys or not _valid_close_conflict_day(day) or marker['carriedSince'] != day
                or not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
                or not isinstance(run, str) or not re.fullmatch(r'[1-9][0-9]*', run)
                or marker['reason'] not in daily_carry.REASONS or daily.get('src') != source or row.get('priceSource') != source
                or not isinstance(daily.get('carriedSource'), str) or not daily['carriedSource'] or daily['carriedSource'] == source
                or daily.get('phase') != 'closed' or 'independentCloseProof' in daily or 'yahooMetaClose' in daily
                or 'providerCloseConflict' in row or selection.get('method') != method or selection.get('sourcePhase') != 'closed'
                or row.get('stale') is True or row.get('pricePhase') != 'closed'
                or 'priceObservedAt' not in row or row['priceObservedAt'] is not None
                or not number(row.get('price')) or row['price'] <= 0
                or quote.get('useQuote') is not False or quote.get('reason') != 'carried_daily_quote_order_unproven'
                or any(key not in quote or quote[key] is not None for key in ('completedBoundaryUTC', 'boundaryKind'))
                or annotation.get('status') != 'carried_daily'
                or any(value != day for value in (row.get('ld'), row.get('metricAsOf'), row.get('priceAsOf'), daily.get('asOf'),
                    selection.get('selectedDate'), selection.get('sourceAsOf'), annotation.get('quoteDate')))):
            fail()
        if baseline is not None and baseline != (sha, run):
            fail()
        baseline = sha, run
        reviewed = daily_carry.carry_calendar(symbol, clock)
        if not reviewed:
            fail()
        context, spec = reviewed
        expected = context['expectedCompletedDate']
        received = _close_conflict_receipt_seconds(daily.get('receivedAt'))
        if (not expected or context['confidence'] not in daily_carry.CONFIRMED_CALENDARS
                or any(annotation.get(key) != context[key] for key in ('exchange', 'timezone', 'confidence', 'expectedCompletedDate'))
                or daily.get('timezone') != context['timezone'] or received is None or received > clock.timestamp()
                or day not in (expected, daily_carry.previous_completed_date(symbol, clock))):
            fail()
        close = calendar.session_close(spec, dt.date.fromisoformat(day))
        if received < close.timestamp():
            fail()
        for metric in covered_metrics:
            metric_coverage = [item for item in coverage if (item.get('kind'), item.get('symbol'), item.get('metric')) == ('company', symbol, metric)]
            if len(metric_coverage) != 1 or metric_coverage[0] not in carry_coverage:
                fail()
        markers[symbol] = marker
        carried_companies[symbol] = row
    for item in carry_coverage:
        symbol = item.get('symbol')
        metric = item.get('metric')
        if (item.get('kind') != 'company' or not isinstance(symbol, str) or symbol not in markers
                or not isinstance(metric, str) or metric not in covered_metrics or item.get('source') != source
                or item.get('date') != markers[symbol]['date']):
            fail()
        value = carried_companies[symbol].get(covered_metrics[metric])
        expected_coverage = ('partial', reason) if value is not None else ('missing', 'missing_or_incompatible')
        if (item.get('status'), item.get('reason')) != expected_coverage:
            fail()
    for item in summary['companies']:
        item = fields(item)
        symbol = item.get('symbol')
        if (set(item) != marker_keys | {'symbol'} or not isinstance(symbol, str) or symbol not in markers
                or any(item[key] != markers[symbol][key] for key in marker_keys)):
            fail()
        del markers[symbol]


def validate_carried_daily_baseline(data, clock, manifest, baseline, proof):
    if 'carriedDaily' not in data['meta']:
        return
    previous_rows = {row['sym']: row for row in baseline['companies']}
    for row in data['companies']:
        if 'carried' not in row:
            continue
        marker = row['carried']
        verified = daily_carry.select_carry(row, previous_rows.get(row['sym']), proof['productionSHA'],
                                           manifest['runId'], marker['reason'], clock)
        if verified is None:
            raise BundleError('carried_daily_baseline_mismatch')
        metrics, provenance, expected_marker = verified
        if (expected_marker != marker or provenance != row['provenance']['daily']
                or any(row.get(key) != value for key, value in metrics.items())):
            raise BundleError('carried_daily_baseline_mismatch')


def validate_yahoo_meta_closes(data, clock):
    from market_calendar import context

    def fields(value):
        return value if isinstance(value, dict) else {}

    rows = fields(data).get('companies')
    for row in rows if isinstance(rows, list) else ():
        row = fields(row)
        daily = fields(fields(row.get('provenance')).get('daily'))
        source = daily.get('src') == yahoo_meta_close.SOURCE
        marked = 'yahooMetaClose' in daily
        fallback_price = row.get('priceSource') == yahoo_meta_close.SOURCE
        if not (source or marked or fallback_price):
            continue
        proof = daily.get('yahooMetaClose')
        symbol = row.get('sym')
        if not source or not yahoo_meta_close.valid_proof(proof, symbol, clock):
            raise BundleError('yahoo_meta_close_binding_mismatch')
        calendar = fields(row.get('marketCalendar'))
        exchange = context(symbol, clock)
        selection = fields(daily.get('snapshotSelection'))
        day = proof['date']
        received = _close_conflict_receipt_seconds(proof['receivedAt'])
        if (daily.get('phase') != 'closed' or daily.get('returnBasis') != 'yahoo-adjclose'
                or 'independentCloseProof' in daily or 'providerCloseConflict' in row
                or daily.get('receivedAt') != proof['receivedAt'] or received is None
                or not 0 <= clock.timestamp() - received <= 36 * 3600
                or daily.get('timezone') != exchange['timezone'] or calendar.get('exchange') != exchange['exchange']
                or calendar.get('timezone') != exchange['timezone'] or calendar.get('confidence') != exchange['confidence']
                or selection.get('method') != 'latest-completed-per-market' or selection.get('sourcePhase') != 'closed'
                or any(row.get(key) is not None for key in ('r1d', 'r5', 'r20', 'r60', 'ytd', 'dd52', 'hi52'))
                or any(value != day for value in (row.get('ld'), row.get('metricAsOf'), daily.get('asOf'),
                    calendar.get('quoteDate'), calendar.get('expectedCompletedDate'), selection.get('selectedDate'),
                    selection.get('sourceAsOf')))):
            raise BundleError('yahoo_meta_close_binding_mismatch')
        if fallback_price:
            expected_price = round(proof['price'], 3 if proof['price'] < 10 else 2)
            if (not yahoo_meta_close.positive_price(row.get('price')) or row['price'] != expected_price
                    or row.get('priceAsOf') != day or row.get('pricePhase') != 'closed'
                    or 'priceObservedAt' not in row or row['priceObservedAt'] is not None
                    or fields(row.get('priceSelection')).get('useQuote') is not False):
                raise BundleError('yahoo_meta_close_binding_mismatch')
        else:
            observed = _close_conflict_receipt_seconds(row.get('priceObservedAt'))
            price_selection = fields(row.get('priceSelection'))
            if (not yahoo_meta_close.positive_price(row.get('price')) or not isinstance(row.get('priceSource'), str)
                    or not row['priceSource'] or observed is None or row.get('pricePhase') != 'intraday'
                    or not proof['nextSessionOpen'] < observed <= clock.timestamp()
                    or price_selection.get('useQuote') is not True
                    or price_selection.get('boundaryKind') != 'later_session_start_upper_bound'
                    or _close_conflict_receipt_seconds(price_selection.get('completedBoundaryUTC')) != proof['nextSessionOpen']
                    or row.get('priceAsOf') != dt.datetime.fromtimestamp(observed, dt.UTC)
                        .astimezone(ZoneInfo(exchange['timezone'])).date().isoformat()):
                raise BundleError('yahoo_meta_close_binding_mismatch')


def validate_provider_close_conflicts(data):
    """Bind optional conflict markers to the selected, calendar-expected close."""
    def fields(value):
        return value if isinstance(value, dict) else {}

    rows = fields(data).get('companies')
    for row in rows if isinstance(rows, list) else ():
        row = fields(row)
        daily = fields(fields(row.get('provenance')).get('daily'))
        selection = fields(daily.get('snapshotSelection'))
        marked = 'providerCloseConflict' in row
        fallback = selection.get('method') == PROVIDER_CLOSE_CONFLICT_METHOD
        if not marked and not fallback:
            continue
        marker = fields(row.get('providerCloseConflict'))
        calendar = fields(row.get('marketCalendar'))
        selected, conflict = row.get('ld'), marker.get('date')
        end = marker.get('sessionEnd')
        received = _close_conflict_receipt_seconds(marker.get('receivedAt'))
        if (not marked or not fallback or set(marker) != {'date', 'sessionEnd', 'receivedAt'}
                or not _valid_close_conflict_day(selected) or not _valid_close_conflict_day(conflict)
                or conflict <= selected or selection.get('sourceAsOf') != conflict
                or selection.get('sourcePhase') != 'closed' or daily.get('phase') != 'closed'
                or any(value != selected for value in (selection.get('selectedDate'), row.get('metricAsOf'),
                    daily.get('asOf'), calendar.get('quoteDate'), calendar.get('expectedCompletedDate')))
                or calendar.get('confidence') not in ('official', 'rule_based')
                or daily.get('receivedAt') != marker.get('receivedAt')
                or type(end) not in (int, float) or not 0 < end <= (1 << 53) - 1
                or received is None or end > received):
            raise BundleError('provider_close_conflict_binding_mismatch')


def validate_close_proofs(D, proofs, execution, clock):
    """Bind the independently checked terminal close to this exact output/run.

    No new field is required for the existing provider-only path. The official
    proof is never accepted as a standalone boolean or used for other symbols.
    """
    rows = D.get('companies', [])
    selected = [(row, (row.get('provenance') or {}).get('daily') or {})
                for row in rows if isinstance(row, dict)
                and 'independentCloseProof' in ((row.get('provenance') or {}).get('daily') or {})]
    if proofs is None and not selected:
        return
    try:
        from decimal import Decimal
        from equity_close_proof import valid_summary
        if (not isinstance(proofs, dict) or set(proofs) != {'2383.TW'}
                or len(selected) != 1 or sum(row.get('sym') == '2383.TW' for row in rows) != 1):
            raise ValueError
        row, daily = selected[0]
        proof = proofs['2383.TW']
        if (row.get('sym') != '2383.TW' or row.get('cur') != 'TWD'
                or daily.get('independentCloseProof') != proof
                or not valid_summary(proof, now=clock, execution=execution)):
            raise ValueError
        day = proof['day']
        selection = daily.get('snapshotSelection') or {}
        calendar = row.get('marketCalendar') or {}
        if (any(row.get(key) != day for key in ('ld', 'metricAsOf', 'priceAsOf'))
                or daily.get('asOf') != day or daily.get('src') != 'yahoo'
                or daily.get('phase') != 'closed' or daily.get('returnBasis') != 'yahoo-adjclose'
                or daily.get('timezone') != 'Asia/Taipei'
                or daily.get('receivedAt') != proof['parserReceivedAt']
                or selection.get('sourcePhase') != 'unknown'
                or selection.get('sourceAsOf') != day or selection.get('selectedDate') != day
                or row.get('pricePhase') != 'closed' or row.get('priceSource') != 'yahoo'
                or row.get('priceObservedAt') is not None
                or (row.get('priceSelection') or {}).get('useQuote') is not False
                or not isinstance(row.get('price'), (int, float)) or isinstance(row.get('price'), bool)
                or Decimal(str(row.get('price'))) != Decimal(proof['close'])
                or calendar.get('exchange') != 'XTAI' or calendar.get('confidence') != 'official'
                or calendar.get('expectedCompletedDate') != day or calendar.get('quoteDate') != day):
            raise ValueError
    except (KeyError, TypeError, ValueError, ArithmeticError):
        raise BundleError('independent_close_proof_binding_mismatch') from None


def validate_research_snapshot(snapshot, D, fixed_clock):
    """Bind canonical, sanitized last-good bytes to the immutable DATA receipt."""
    check_sensitive(snapshot)
    if (snapshots.load_last_good(snapshot) is None or snapshot.get('contractVersion') != '3.0' or
            set(snapshot) != {'schemaVersion', 'contractVersion', 'notionVersion', 'builtAt', 'tables'} or
            set(snapshot['tables']) != set(snapshots.TABLES) or snapshot['builtAt'] != fixed_clock):
        raise BundleError('research_snapshot_schema')
    for table in snapshot['tables'].values():
        if set(table) != {'source', 'fetchedAt', 'schemaHash', 'rows'}:
            raise BundleError('research_snapshot_schema')
        if table['rows'] != sorted(table['rows'], key=lambda row: row['id']):
            raise BundleError('research_snapshot_order')
        if any(set(row) != {'id', 'created_time', 'last_edited_time', 'props'} for row in table['rows']):
            raise BundleError('research_snapshot_row_shape')
    blob = snapshots.canonical_json(snapshot).encode('utf-8')
    if D.get('meta', {}).get('notion', {}).get('snapshotSHA256') != digest(blob):
        raise BundleError('research_snapshot_binding_mismatch')
    return blob


def notion_summary(D):
    n = D['meta']['notion']
    return {key: n[key] for key in ('source', 'requests', 'counts', 'fallbackTables')} | {
        'warningCount': len(n['warnings']), 'quarantinedCount': len(n['quarantined'])}


def write_bundle(out_dir, D, receipt, clock, research_snapshot=None):
    """Validate all bytes first, then atomically expose the allowlisted archive."""
    validate_binding(D, receipt, clock)
    payload = {'DATA.json': encoded(D), 'receipt.json': encoded(receipt)}
    if research_snapshot is not None:
        payload[SNAPSHOT] = validate_research_snapshot(research_snapshot, D, clock.isoformat())
    elif 'notion' in D.get('meta', {}):
        raise BundleError('research_snapshot_required')
    if len(payload['receipt.json']) > MAX_RECEIPT:
        raise BundleError('receipt_size_limit')
    if sum(map(len, payload.values())) > MAX_BUNDLE:
        raise BundleError('bundle_size_limit')
    payload['index.html'] = render_archive(D, receipt['publication']['blockers'])
    if embedded_data(payload['index.html']) != D:
        raise BundleError('html_data_mismatch')
    if SECRET_VALUE.search(payload['index.html'].decode()):
        raise BundleError('sensitive_rendered_value')
    manifest = {
        'schemaVersion': 2 if research_snapshot is not None else 1, 'purpose': 'interface-acceptance-not-publication',
        'dataClassification': classification(D), 'publicationAuthorized': False,
        'execution': {k: receipt['execution'][k] for k in
                      ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')},
        'fixedClock': clock.isoformat(), 'selectedDate': D['meta']['asOf'],
        'snapshotPolicy': D['meta']['snapshot'].get('policy'),
        'priceDateRange': D['meta'].get('priceDateRange',[]),
        'metricAsOfByMarket': D['meta'].get('asOfByMarket',{}),
        'blockers': receipt['publication']['blockers'], 'retentionDays': 7,
        'maxTotalBytes': MAX_BUNDLE,
        'files': {name: {'bytes': len(payload[name]), 'sha256': digest(payload[name])}
                  for name in payload},
        'totalBytes': 0,
    }
    if research_snapshot is not None:
        manifest['researchSnapshotSHA256'] = digest(payload[SNAPSHOT])
    # A manifest cannot contain its own hash. Its size is included in the limit;
    # the external completion log records its SHA256 along with the other files.
    for _ in range(10):
        blob = encoded(manifest)
        total = sum(map(len, payload.values())) + len(blob)
        if total == manifest['totalBytes']:
            break
        manifest['totalBytes'] = total
    else:
        raise BundleError('manifest_size_unstable')
    payload['manifest.json'] = blob
    if total > MAX_BUNDLE:
        raise BundleError('bundle_size_limit')
    out_dir = Path(out_dir)
    if out_dir.exists() or out_dir.is_symlink():
        raise BundleError('bundle_destination_exists')
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.radar-bundle-', dir=out_dir.parent) as tmp:
        stage = Path(tmp) / 'bundle'
        stage.mkdir()
        for name in payload:
            (stage / name).write_bytes(payload[name])
        verify_bundle(stage)
        atomic_directory_rename(stage, out_dir)
    return {'totalBytes': total, 'files': {name: {'bytes': len(payload[name]),
            'sha256': digest(payload[name])} for name in payload}}


def verify_bundle(directory):
    """Read-only verification used locally and immediately before artifact upload."""
    directory = Path(directory)
    manifest_path = directory/'manifest.json'
    if directory.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
        raise BundleError('bundle_file_allowlist')
    manifest = json.loads(manifest_path.read_text('utf-8'))
    files = (*FILES, SNAPSHOT) if manifest.get('schemaVersion') == 2 else FILES
    if {p.name for p in directory.iterdir()} != set(files):
        raise BundleError('bundle_file_allowlist')
    paths = {name: directory / name for name in files}
    if any(p.is_symlink() or not p.is_file() for p in paths.values()):
        raise BundleError('bundle_file_type')
    total = sum(p.stat().st_size for p in paths.values())
    if total > MAX_BUNDLE or paths['receipt.json'].stat().st_size > MAX_RECEIPT:
        raise BundleError('bundle_size_limit')
    payload = {name: p.read_bytes() for name, p in paths.items()}
    manifest = json.loads(payload['manifest.json'])
    check_sensitive(manifest)
    if (set(manifest) != {'schemaVersion', 'purpose', 'dataClassification', 'publicationAuthorized',
                         'execution', 'fixedClock', 'selectedDate', 'blockers', 'retentionDays',
                         'maxTotalBytes', 'files', 'totalBytes', 'snapshotPolicy', 'priceDateRange', 'metricAsOfByMarket'} | ({'researchSnapshotSHA256'} if manifest.get('schemaVersion') == 2 else set()) or
            manifest.get('schemaVersion') not in (1, 2) or
            manifest.get('purpose') != 'interface-acceptance-not-publication'):
        raise BundleError('bundle_manifest_schema')
    expected = {name: {'bytes': len(payload[name]), 'sha256': digest(payload[name])} for name in files if name != 'manifest.json'}
    if (manifest.get('files') != expected or manifest.get('totalBytes') != total or
            manifest.get('maxTotalBytes') != MAX_BUNDLE or manifest.get('retentionDays') != 7 or
            manifest.get('publicationAuthorized') is not False):
        raise BundleError('bundle_manifest_mismatch')
    D, receipt = json.loads(payload['DATA.json']), json.loads(payload['receipt.json'])
    clock = dt.datetime.fromisoformat(manifest['fixedClock'])
    validate_binding(D, receipt, clock)
    if manifest['schemaVersion'] == 2:
        blob = validate_research_snapshot(json.loads(payload[SNAPSHOT]), D, manifest['fixedClock'])
        if blob != payload[SNAPSHOT] or manifest['researchSnapshotSHA256'] != digest(blob):
            raise BundleError('research_snapshot_bytes_mismatch')
    elif 'notion' in D.get('meta', {}):
        raise BundleError('research_snapshot_required')
    if (manifest['execution'] != {k: receipt['execution'][k] for k in manifest['execution']} or
            set(manifest['execution']) != {'GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'} or
            manifest['selectedDate'] != D['meta']['asOf'] or
            manifest['snapshotPolicy'] != D['meta']['snapshot'].get('policy') or
            manifest['priceDateRange'] != D['meta'].get('priceDateRange',[]) or
            manifest['metricAsOfByMarket'] != D['meta'].get('asOfByMarket',{}) or
            manifest['blockers'] != receipt['publication']['blockers'] or
            manifest['dataClassification'] != classification(D) or
            embedded_data(payload['index.html']) != D or
            payload['index.html'] != render_archive(D, manifest['blockers'])):
        raise BundleError('bundle_content_mismatch')
    return {'totalBytes': total, 'files': {name: {'bytes': len(blob), 'sha256': digest(blob)}
                                         for name, blob in payload.items()}}
