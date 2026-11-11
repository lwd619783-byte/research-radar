"""Check the published Node verifier against reviewed calendar close cases."""
import copy
import datetime as dt
import json
import os
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

SOURCE = 'yahoo-meta-close'
ERROR = 'yahoo_meta_close_binding_mismatch'


def epoch(value):
    return int(dt.datetime.fromisoformat(value).timestamp())


def packet(*, symbol='NVDA', exchange='XNAS', timezone='America/New_York',
           day='2026-11-27', close='2026-11-27T18:00:00Z',
           next_open='2026-11-30T14:30:00Z', clock='2026-11-27T18:05:00Z',
           received='2026-11-27T18:04:00.123456Z', confidence='official', price=10.125):
    proof = {'date': day, 'price': price, 'marketTime': epoch(close), 'sessionClose': epoch(close),
             'nextSessionOpen': epoch(next_open), 'receivedAt': received}
    daily = {'src': SOURCE, 'asOf': day, 'receivedAt': received, 'returnBasis': 'yahoo-adjclose',
             'phase': 'closed', 'timezone': timezone, 'yahooMetaClose': proof,
             'snapshotSelection': {'method': 'latest-completed-per-market', 'selectedDate': day,
                                   'sourceAsOf': day, 'sourcePhase': 'closed'}}
    row = {'sym': symbol, 'ld': day, 'metricAsOf': day, 'priceAsOf': day, 'pricePhase': 'closed',
           'priceObservedAt': None, 'priceSource': SOURCE, 'price': round(price, 3 if price < 10 else 2),
           'priceSelection': {'useQuote': False}, 'provenance': {'daily': daily},
           'marketCalendar': {'exchange': exchange, 'timezone': timezone, 'confidence': confidence,
                              'quoteDate': day, 'expectedCompletedDate': day}}
    return {'clock': clock, 'data': {'meta': {}, 'companies': [row]}}


def mutate(base, changes):
    updated = copy.deepcopy(base)
    for path, value in changes.items():
        target = updated
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return updated


class YahooMetaCloseVerifierTests(unittest.TestCase):
    def check_packets(self, accepted, rejected):
        for item in accepted:
            with self.subTest(verifier='python', accepted=item):
                bundle.validate_yahoo_meta_closes(item['data'], dt.datetime.fromisoformat(item['clock']))
        for item in rejected:
            with self.subTest(verifier='python', rejected=item), self.assertRaisesRegex(bundle.BundleError, ERROR):
                bundle.validate_yahoo_meta_closes(item['data'], dt.datetime.fromisoformat(item['clock']))
        script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {checkYahooMetaClose} = require(process.argv[1]);
const calendar = require(process.argv[2]);
const {accepted, rejected} = JSON.parse(fs.readFileSync(0, 'utf8'));
for (const {clock, data} of accepted) checkYahooMetaClose({fixedClock: clock}, data, calendar);
for (const {clock, data} of rejected) {
    assert.throws(() => checkYahooMetaClose({fixedClock: clock}, data, calendar),
        {message: 'yahoo_meta_close_binding_mismatch'});
}
"""
        result = subprocess.run(
            ['node', '-e', script, str(SCRIPTS/'verify-release.cjs'),
             str(SCRIPTS.parent/'data/market_calendar.json')],
            input=json.dumps({'accepted': accepted, 'rejected': rejected}), capture_output=True,
            text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reviewed_early_closes_holidays_dst_and_price_rounding(self):
        early_friday = packet()
        paris_holiday = packet(symbol='SU.PA', exchange='XPAR', timezone='Europe/Paris',
            day='2026-12-24', close='2026-12-24T14:05:00+01:00', next_open='2026-12-28T09:00:00+01:00',
            clock='2026-12-24T14:06:00+01:00', received='2026-12-24T14:05:00.123456+01:00', price=1.0625)
        new_york_dst = packet(day='2026-10-30', close='2026-10-30T16:00:00-04:00',
            next_open='2026-11-02T09:30:00-05:00', clock='2026-10-30T16:05:00-04:00',
            received='2026-10-30T16:04:00-04:00', price=10.005)
        rule_based = packet(day='2027-03-05', close='2027-03-05T16:00:00-05:00',
            next_open='2027-03-08T09:30:00-05:00', clock='2027-03-05T16:05:00-05:00',
            received='2027-03-05T16:04:00-05:00', confidence='rule_based')
        row = ('data', 'companies', 0)
        proof = row + ('provenance', 'daily', 'yahooMetaClose')
        self.check_packets([early_friday, paris_holiday, new_york_dst, rule_based], [
            mutate(early_friday, {proof + ('sessionClose',): epoch('2026-11-27T21:00:00Z')}),
            mutate(paris_holiday, {proof + ('nextSessionOpen',): epoch('2026-12-25T09:00:00+01:00')}),
            mutate(new_york_dst, {proof + ('nextSessionOpen',): epoch('2026-11-02T09:30:00-04:00')}),
            mutate(early_friday, {row + ('price',): 10.13}),
            mutate(paris_holiday, {row + ('price',): 1.063}),
        ])

    def test_invalid_proof_dates_receipts_and_taiwan_are_rejected(self):
        base = packet()
        row = ('data', 'companies', 0)
        daily = row + ('provenance', 'daily')
        proof = daily + ('yahooMetaClose',)
        legacy = mutate(base, {daily + ('src',): 'yahoo', row + ('priceSource',): 'yahoo'})
        del legacy['data']['companies'][0]['provenance']['daily']['yahooMetaClose']
        taiwan = packet(symbol='2383.TW', exchange='XTAI', timezone='Asia/Taipei',
            day='2026-11-26', close='2026-11-26T13:30:00+08:00', next_open='2026-11-27T09:00:00+08:00',
            clock='2026-11-26T13:35:00+08:00', received='2026-11-26T13:34:00+08:00')
        provisional = packet(symbol='688012.SS', exchange='XSHG', timezone='Asia/Shanghai',
            day='2027-03-05', close='2027-03-05T15:00:00+08:00', next_open='2027-03-08T09:30:00+08:00',
            clock='2027-03-05T15:05:00+08:00', received='2027-03-05T15:04:00+08:00',
            confidence='provisional')
        invalid = [
            {daily + ('src',): 'yahoo'},
            {daily + ('yahooMetaClose',): None},
            {proof + ('extra',): True},
            {proof + ('price',): '10.125'},
            {proof + ('marketTime',): epoch('2026-11-27T18:00:00Z') + 0.5},
            {proof + ('marketTime',): epoch('2026-11-27T17:59:59Z')},
            {proof + ('marketTime',): epoch('2026-11-30T14:30:00Z')},
            {row + ('marketCalendar', 'confidence'): 'provisional'},
            {row + ('ld',): '2026-11-26'},
            {row + ('r5',): 0.05},
            {row + ('hi52',): 12},
            {daily + ('snapshotSelection', 'sourceAsOf'): '2026-11-26'},
            {daily + ('timezone',): 'Europe/Paris'},
            {row + ('marketCalendar', 'exchange'): 'XNYS'},
            {row + ('providerCloseConflict',): {}},
            {daily + ('independentCloseProof',): {}},
            {('clock',): '2026-11-29T06:04:00.123457Z'},
            {('clock',): '2026-11-30T21:05:00Z'},
        ]
        for received in ('2026-11-27T18:04:00', '2026-11-27T18:04:00+00:60',
                         '2026-11-27T17:59:59.999999Z', '2026-11-27T18:05:00.000001Z'):
            invalid.append({daily + ('receivedAt',): received, proof + ('receivedAt',): received})
        age_limit = mutate(base, {('clock',): '2026-11-29T06:04:00.123456Z'})
        self.check_packets([base, legacy, age_limit],
                           [taiwan, provisional, *(mutate(base, changes) for changes in invalid)])

    def test_only_a_newer_intraday_quote_may_replace_the_display_price(self):
        row = ('data', 'companies', 0)
        selection = {'useQuote': True, 'completedBoundaryUTC': '2026-11-30T14:30:00+00:00',
                     'boundaryKind': 'later_session_start_upper_bound'}
        intraday = mutate(packet(clock='2026-11-30T14:35:00Z', received='2026-11-30T14:33:00Z'), {
            row + ('price',): 12.3456, row + ('priceSource',): 'yahoo-quote',
            row + ('pricePhase',): 'intraday', row + ('priceAsOf',): '2026-11-30',
            row + ('priceObservedAt',): '2026-11-30T14:31:00+00:00',
            row + ('priceSelection',): selection,
        })
        self.check_packets([intraday], [
            mutate(intraday, {row + ('priceObservedAt',): '2026-11-30T14:30:00Z'}),
            mutate(intraday, {row + ('priceObservedAt',): '2026-11-30T14:35:00.000001Z'}),
            mutate(intraday, {row + ('priceSelection', 'completedBoundaryUTC'): '2026-11-30T14:29:59Z'}),
            mutate(intraday, {row + ('pricePhase',): 'closed'}),
        ])

    def test_materialized_verifier_runs_in_ci_and_vercel_without_calendar_sidecar(self):
        def render(data, public, info):
            public.mkdir()
            html = ('当前为验收版本，自动刷新与发布未启用。'
                    f'<script>const DATA={json.dumps(data)};</script>'
                    f'<script id="radar-operations">const OPERATIONS={json.dumps(info)};</script>')
            (public/'index.html').write_text(html, encoding='utf-8')
            (public/'robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
            (public/'vercel.json').write_text('{}', encoding='utf-8')

        item = packet()
        data = item['data']
        info = {'sourceSHA': 'a' * 40, 'dataSHA256': bundle.data_digest(data)}
        receipt = {'execution': {'GITHUB_SHA': info['sourceSHA'], 'GITHUB_RUN_ID': '123'},
                   'fixedClock': item['clock']}
        with tempfile.TemporaryDirectory() as temp, patch.object(release.build, 'render', side_effect=render):
            root = Path(temp)
            release._materialize(root, root, data, receipt, info, [], None)
            self.assertEqual({p.name for p in root.iterdir()},
                             {'public', 'history.json', 'vercel.json', 'verify-release.cjs', 'release.json'})
            env = os.environ | {'VERCEL_ENV': 'production', 'VERCEL_GIT_COMMIT_REF': 'production',
                                'VERCEL_GIT_COMMIT_SHA': 'b' * 40}
            for args in (['--check-only'], []):
                result = subprocess.run(['node', 'verify-release.cjs', *args], cwd=root, env=env,
                                        capture_output=True, text=True, encoding='utf-8', timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root/'public/version.json').read_bytes())['productionSHA'], 'b' * 40)
