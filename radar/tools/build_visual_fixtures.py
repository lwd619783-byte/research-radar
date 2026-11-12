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
from acceptance_bundle import validate_provider_close_conflicts

STATES = ('W03', 'W06', 'D01', 'T01', 'R12')


def provider_close_conflict_fixture(data):
    """Render an invented early-close marker on the already selected prior close."""
    value = copy.deepcopy(data)
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
    with tempfile.TemporaryDirectory(prefix='radar-visual-conflict-') as directory:
        html = build.render(value, Path(directory)).read_bytes()
    return {'DATA': value, 'data': json.dumps(value, ensure_ascii=False, allow_nan=False),
            'html': html, 'exit': 0}


def build_pages(destination: Path) -> dict:
    """Use the real fixture pipeline once per page; never run the full case matrix."""
    destination.mkdir(parents=True, exist_ok=True)
    baseline = run_fixture()
    cases = {case['id']: case for case in CASES['cases']}
    results = {'baseline': baseline}
    for name in STATES:
        results[name] = run_fixture(cases[name]['mutations'], baseline['snapshot_object'])
    results['provider-close-conflict'] = provider_close_conflict_fixture(baseline['DATA'])
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
