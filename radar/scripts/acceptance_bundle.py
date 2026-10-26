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

import build
import research_snapshot as snapshots

MAX_BUNDLE = 10_000_000  # Decimal 10 MB, including manifest; never truncate.
MAX_RECEIPT = 512 * 1024
PAYLOADS = ('DATA.json', 'index.html', 'receipt.json')
FILES = (*PAYLOADS, 'manifest.json')
SNAPSHOT = 'research-snapshot.json'
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
