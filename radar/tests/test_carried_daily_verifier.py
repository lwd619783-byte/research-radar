"""Check that Python and Node agree on the published daily carry contract."""
import copy
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import acceptance_bundle as bundle
import production_release as release

CARRY = 'verified-release-carry'
METHOD = 'carried-from-verified-release'
COVERAGE_REASON = 'carried_from_verified_release'
BAD_BINDING = 'carried_daily_binding_mismatch'
EXCESS = 'carried_daily_exceeds_limit'


def packet(total=10, count=1, *, date='2026-11-27', expected='2026-11-30',
           clock='2026-11-30T18:15:00+01:00', received='2026-11-27T18:00:00+01:00'):
    rows = []
    entries = []
    coverage = []
    for index in range(total):
        sym = f'C{index}.DE'
        row = {'sym': sym}
        if index < count:
            marker = {'date': date, 'carriedSince': date, 'baselineProductionSHA': 'b' * 40,
                      'baselineRunId': '123', 'reason': 'provider_daily_close_null'}
            daily = {'src': CARRY, 'carriedSource': 'yahoo-meta-close', 'asOf': date,
                     'receivedAt': received, 'returnBasis': 'yahoo-adjclose',
                     'phase': 'closed', 'timezone': 'Europe/Berlin',
                     'snapshotSelection': {'method': METHOD, 'selectedDate': date,
                                           'sourceAsOf': date, 'sourcePhase': 'closed'}}
            row.update(carried=marker, ld=date, metricAsOf=date, priceAsOf=date,
                       pricePhase='closed', priceObservedAt=None, priceSource=CARRY, price=12.34,
                       r5=None, r20=None, r60=None, ytd=None, hi52=None,
                       priceSelection={'useQuote': False, 'reason': 'carried_daily_quote_order_unproven',
                                       'completedBoundaryUTC': None, 'boundaryKind': None},
                       provenance={'daily': daily},
                       marketCalendar={'exchange': 'XETR', 'timezone': 'Europe/Berlin',
                                       'confidence': 'official', 'status': 'carried_daily',
                                       'quoteDate': date, 'expectedCompletedDate': expected})
            entries.append({'symbol': sym, **marker})
            for metric in ('daily', 'price', 'r5', 'r20', 'r60', 'ytd', 'high52'):
                available = metric in ('price', 'daily')
                coverage.append({'kind': 'company', 'symbol': sym, 'metric': metric,
                                 'status': 'partial' if available else 'missing',
                                 'reason': COVERAGE_REASON if available else 'missing_or_incompatible',
                                 'date': date, 'source': CARRY})
        rows.append(row)
    meta = {'coverage': coverage, 'blockers': [],
            'snapshot': {'policy': 'latest-quote-and-market-completed-daily', 'status': 'complete',
                         'requiredCompanies': total, 'selectedCompanies': total}}
    if entries:
        meta['carriedDaily'] = {'companies': entries, 'count': count, 'limit': total // 10}
    return {'clock': clock, 'data': {'meta': meta, 'companies': rows}}


def mutate(item, path, value):
    result = copy.deepcopy(item)
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return result


class CarriedDailyVerifierTests(unittest.TestCase):
    def check_packets(self, accepted, rejected):
        for item in accepted:
            bundle.validate_carried_daily(item['data'], dt.datetime.fromisoformat(item['clock']))
        for index, (item, code) in enumerate(rejected):
            with self.subTest(rejected=index), self.assertRaisesRegex(bundle.BundleError, code):
                bundle.validate_carried_daily(item['data'], dt.datetime.fromisoformat(item['clock']))
        script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {checkCarriedDaily} = require(process.argv[1]);
const calendar = require(process.argv[2]);
const {accepted, rejected} = JSON.parse(fs.readFileSync(0, 'utf8'));
for (const {clock, data} of accepted) checkCarriedDaily({fixedClock: clock}, data, calendar);
for (const [index, [{clock, data}, message]] of rejected.entries()) {
    assert.throws(() => checkCarriedDaily({fixedClock: clock}, data, calendar), {message}, `rejected case ${index}`);
}
"""
        result = subprocess.run(
            ['node', '-e', script, str(SCRIPTS/'verify-release.cjs'),
             str(SCRIPTS.parent/'data/market_calendar.json')],
            input=json.dumps({'accepted': accepted, 'rejected': rejected}), capture_output=True,
            text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_expected_and_previous_session_across_weekend_and_holiday(self):
        monday = packet()
        # Xetra has consecutive 12/24–12/25 closures, then the weekend.
        holiday = packet(date='2026-12-23', expected='2026-12-28',
                         received='2026-12-23T17:31:00+01:00', clock='2026-12-28T18:00:00+01:00')
        expected = packet(date='2026-11-30', received='2026-11-30T17:30:00+01:00')
        two_sessions_old = packet(date='2026-12-22', expected='2026-12-28',
                                  received='2026-12-22T17:31:00+01:00', clock='2026-12-28T18:00:00+01:00')
        closed_day = packet(date='2026-12-25', expected='2026-12-28',
                            received='2026-12-25T17:31:00+01:00', clock='2026-12-28T18:00:00+01:00')
        self.check_packets([monday, holiday, expected], [(two_sessions_old, BAD_BINDING), (closed_day, BAD_BINDING)])

    def test_cap_and_snapshot_bind_to_actual_companies(self):
        row_count = ('data', 'meta', 'snapshot', 'requiredCompanies')
        summary_limit = ('data', 'meta', 'carriedDaily', 'limit')
        self.check_packets([packet(count=0), packet(20, 2)], [
            (packet(19, 2), EXCESS),
            (packet(9, 1), EXCESS),
            (mutate(packet(), row_count, 74), BAD_BINDING),
            (mutate(packet(), summary_limit, 7), BAD_BINDING),
            (mutate(packet(count=0), ('data', 'meta', 'blockers'), [EXCESS]), EXCESS),
        ])

    def test_rejects_unpaired_provenance_bad_baseline_and_price_or_coverage_conflicts(self):
        item = packet()
        row = ('data', 'companies', 0)
        daily = row + ('provenance', 'daily')
        summary = ('data', 'meta', 'carriedDaily')
        coverage = ('data', 'meta', 'coverage', 0)
        absent_return_coverage = ('data', 'meta', 'coverage', 2)
        mixed = packet(20, 2)
        changed = 'c' * 40
        mixed['data']['companies'][1]['carried']['baselineProductionSHA'] = changed
        mixed['data']['meta']['carriedDaily']['companies'][1]['baselineProductionSHA'] = changed
        self.check_packets([item], [(mixed, BAD_BINDING), *[
            (mutate(item, path, value), BAD_BINDING) for path, value in [
                (row + ('carried', 'carriedSince'), '2026-11-30'),
                (row + ('carried', 'reason'), 'future_date'),
                (row + ('carried', 'baselineRunId'), '0'),
                (row + ('priceSource',), 'yahoo'),
                (row + ('priceSelection', 'useQuote'), True),
                (row + ('providerCloseConflict',), {}),
                (row + ('marketCalendar', 'expectedCompletedDate'), '2026-11-27'),
                (daily + ('carriedSource',), CARRY),
                (daily + ('independentCloseProof',), {}),
                (daily + ('receivedAt',), '2026-11-27T17:29:59.999999+01:00'),
                (daily + ('receivedAt',), '2026-11-27T18:00:00'),
                (summary + ('companies', 0, 'symbol'), 'C1.DE'),
                (coverage + ('status',), 'complete'),
                (coverage + ('symbol',), 'C1.DE'),
                (row + ('r5',), 0.01),
                (absent_return_coverage + ('reason',), COVERAGE_REASON),
                (absent_return_coverage + ('source',), 'yahoo'),
            ]
        ]])

    def test_materialized_verifier_rechecks_carry_with_reviewed_calendar(self):
        def render(data, public, info):
            public.mkdir()
            html = ('当前为验收版本，自动刷新与发布未启用。'
                    f'<script>const DATA={json.dumps(data)};</script>'
                    f'<script id="radar-operations">const OPERATIONS={json.dumps(info)};</script>')
            (public/'index.html').write_text(html, encoding='utf-8')
            (public/'robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
            (public/'vercel.json').write_text('{}', encoding='utf-8')

        cases = [(packet(), True),
                 (packet(clock='2026-12-01T18:15:00+01:00', expected='2026-12-01'), False)]
        for item, accepted in cases:
            data = item['data']
            info = {'sourceSHA': 'a' * 40, 'dataSHA256': bundle.data_digest(data)}
            receipt = {'execution': {'GITHUB_SHA': info['sourceSHA'], 'GITHUB_RUN_ID': '123'},
                       'fixedClock': item['clock']}
            with tempfile.TemporaryDirectory() as temp, patch.object(release.build, 'render', side_effect=render):
                root = Path(temp)
                release._materialize(root, root, data, receipt, info, [], None)
                result = subprocess.run(['node', 'verify-release.cjs', '--check-only'], cwd=root,
                                        capture_output=True, text=True, encoding='utf-8', timeout=15)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                if not accepted:
                    self.assertIn(BAD_BINDING, result.stderr)
