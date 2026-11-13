"""Build isolated, non-publishable V3 browser pages without network or credentials."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/tests'))
from test_notion_v3 import CASES, FIXTURES, read_json, run_fixture
import build
import daily_carry
from acceptance_bundle import validate_carried_daily, validate_provider_close_conflicts

STATES = ('W03', 'W06', 'D01', 'T01', 'R12')


def mark_provider_close_conflict(value):
    """Add an invented early-close marker to the already selected prior close."""
    company = next(row for row in value['companies'] if row['sym'] == 'ENR.DE')
    daily = company['provenance']['daily']
    selection = daily['snapshotSelection']
    received = dt.datetime.fromisoformat(daily['receivedAt'])
    now = dt.datetime.fromisoformat(value['meta']['generatedAt'])
    company['providerCloseConflict'] = {'date': selection['sourceAsOf'],
        'sessionEnd': int(received.timestamp()) - 120, 'receivedAt': daily['receivedAt']}
    company['marketCalendar'] = build.market_calendar.annotate(
        company['sym'], daily['asOf'], now, completed=True)
    selection.update(method=build.latest.PROVIDER_CLOSE_CONFLICT_METHOD, sourcePhase='closed')
    validate_provider_close_conflicts(value)


def render_review_fixture(value):
    with tempfile.TemporaryDirectory(prefix='radar-visual-') as directory:
        html = build.render(value, Path(directory)).read_bytes()
    return {'DATA': value, 'data': json.dumps(value, ensure_ascii=False, allow_nan=False),
            'html': html, 'exit': 0}


def carried_daily_fixture(data, *, at_limit=False):
    value = copy.deepcopy(data)
    now = dt.datetime.fromisoformat(value['meta']['generatedAt'])
    limit = value['meta']['snapshot']['requiredCompanies'] // 10
    count = limit if at_limit else 1
    sample = ('YJKJ', 'ANET', 'NTB', 'AVGO')
    rows = {row['id']: row for row in value['companies']}
    if count > len(sample):
        raise RuntimeError('Extend the visual carry sample to match the fixture company limit')
    companies = []
    for company_id in sample[:count]:
        company = rows[company_id]
        marker = {'date': company['ld'], 'carriedSince': company['ld'],
                  'baselineProductionSHA': 'a' * 40, 'baselineRunId': '123',
                  'reason': daily_carry.CLOSE_NULL}
        company['carried'] = marker
        daily = company['provenance']['daily']
        # The fixed preview clock predates the original fixture receipts.
        spec = build.market_calendar.calendar_data()['exchanges'][
            build.market_calendar.exchange_for(company['sym'])]
        close = build.market_calendar.session_close(spec, dt.date.fromisoformat(company['ld']))
        daily.update(carriedSource=daily['src'], src=daily_carry.SOURCE,
                     receivedAt=(close + dt.timedelta(minutes=1)).isoformat(),
                     snapshotSelection={'method': daily_carry.CARRY_SELECTION_METHOD,
                         'selectedDate': company['ld'], 'sourceAsOf': company['ld'],
                         'sourcePhase': 'closed'})
        annotation = build.market_calendar.annotate(
            company['sym'], company['ld'], now, completed=True)
        annotation.update(status='carried_daily', label=None)
        company.update(priceSource=daily_carry.SOURCE, priceObservedAt=None,
                       marketCalendar=annotation, priceSelection={'useQuote': False,
                           'reason': 'carried_daily_quote_order_unproven',
                           'completedBoundaryUTC': None, 'boundaryKind': None})
        for item in value['meta']['coverage']:
            if (item['kind'] == 'company' and item['symbol'] == company['sym']
                    and item['metric'] in ('price', 'daily', 'r5', 'r20', 'r60', 'ytd', 'high52')
                    and item['status'] != 'missing'):
                item.update(source=daily_carry.SOURCE, date=company['ld'],
                            status='partial', reason='carried_from_verified_release')
        companies.append({'symbol': company['sym'], **marker})
    value['meta']['carriedDaily'] = {'companies': companies, 'count': count, 'limit': limit}
    if at_limit:
        mark_provider_close_conflict(value)
    validate_carried_daily(value, now)
    return render_review_fixture(value)


def build_pages(destination: Path) -> dict:
    """Use the real fixture pipeline once per page; never run the full case matrix."""
    destination.mkdir(parents=True, exist_ok=True)
    baseline = run_fixture()
    cases = {case['id']: case for case in CASES['cases']}
    results = {'baseline': baseline}
    for name in STATES:
        results[name] = run_fixture(cases[name]['mutations'], baseline['snapshot_object'])
    conflict = copy.deepcopy(baseline['DATA'])
    mark_provider_close_conflict(conflict)
    results['provider-close-conflict'] = render_review_fixture(conflict)
    results['carried-daily-one'] = carried_daily_fixture(baseline['DATA'])
    results['carried-daily-at-limit'] = carried_daily_fixture(baseline['DATA'], at_limit=True)
    manifest = {'kind': 'offline-review-only', 'publishable': False,
                'fixedClock': CASES['as_of'], 'pages': {}}
    for name, result in results.items():
        if result['exit'] != 0 or not result['html']:
            raise RuntimeError(f'Visual fixture {name} did not build')
        if not result['DATA']['meta'].get('reviewPreview'):
            raise RuntimeError(f'Visual fixture {name} lost its review-only marker')
        page_dir = destination / name
        page_dir.mkdir(exist_ok=True)
        (page_dir / 'index.html').write_bytes(result['html'])
        (page_dir / 'DATA.json').write_text(result['data'], encoding='utf-8')
        manifest['pages'][name] = {
            'path': f'{name}/index.html',
            'sha256': hashlib.sha256(result['html']).hexdigest(),
            'fixedClock': result['DATA']['meta']['generatedAt'],
        }
    # Compatibility is a browser-input test, not a release build. The untouched
    # V2 quote fixture contains retired text fields, so it must not bypass the
    # production output scanner or be offered as a publishable bundle.
    legacy = read_json(FIXTURES / 'quotes/data-2026-10-21.json')
    (destination / 'legacy-DATA.json').write_text(
        json.dumps(legacy, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (destination / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    manifest = build_pages(args.out)
    print(f"Built {len(manifest['pages'])} offline visual pages; publishable=false")


if __name__ == '__main__':
    main()
