"""Independent P2 reproductions and complete, synthetic main-path contracts."""
import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_integrity import NOW, bars, build, dataset, months, quotes, record, financial_evidence


def monthly_record(day='2026-10-16', denominator=False):
    b = [[m, 100. if denominator else 90. + i % 21] for i, (m, _) in enumerate(months())]
    b[-1][1] = 100.
    return record(bars=b, src='tencent', asOf=day,
                  current={'date': day, 'close': 100., 'src': 'tencent'})


def complete_dataset():
    data, mk = dataset()
    for c in data['companies']:
        c.update(revg=20., earng=15., gm=30.)  # Synthetic inputs; never written to TOML.
        c['financial'] = financial_evidence()
        mk['daily'][c['sym']] = record(bars=bars(), priceBasis='raw', returnBasis='synthetic-adjusted',
                                      asOf='2026-10-16', phase='closed', src='synthetic')
        mk['quote'][c['sym']] = record(marketCap=1e10, trailingPE=20., currency=c['cur'], src='yahoo',
            regularMarketTime=dt.datetime(2026, 10, 16, 12, tzinfo=dt.UTC).timestamp())
        if c['cur'] != 'USD':
            mk['fx'][c['cur']] = record(value=7., asOf='2026-10-16', src='synthetic')
    for x in data['config']['indices']:
        mk['index'][x['symbol']] = record(price=3000., chg=.01, date='2026-10-16', phase='closed', src='synthetic')
    mk['ratio'] = {'cyb': monthly_record(), 'hl': monthly_record(denominator=True)}
    return data, mk


class QuoteMergeTests(unittest.TestCase):
    def test_quote_same_day_and_cross_day_regression_preserves_record_and_receipt(self):
        timestamp = dt.datetime(2026, 10, 16, 20, tzinfo=dt.UTC).timestamp()
        for delta in (60, 86400):
            with self.subTest(seconds=delta):
                old = record(regularMarketTime=timestamp, marketCap=1e10, src='yahoo')
                old['receivedAt'] = (NOW-dt.timedelta(hours=2)).isoformat()
                new = record(regularMarketTime=timestamp-delta, marketCap=9e9, src='yahoo')
                merged = build.merge({'quote': {'T': new}}, {'quote': {'T': old}})
                self.assertIs(merged['quote']['T'], old)
                self.assertEqual(merged['quote']['T']['receivedAt'], old['receivedAt'])

    def test_quote_missing_or_invalid_time_cannot_replace_or_refresh(self):
        old = record(regularMarketTime=1792180800, marketCap=1e10)
        for timestamp in (None, '1792180801', True, float('nan'), float('inf'), -1):
            with self.subTest(timestamp=timestamp):
                new = record(regularMarketTime=timestamp, marketCap=9e9)
                self.assertIs(build.merge({'quote': {'T': new}}, {'quote': {'T': old}})['quote']['T'], old)

    def test_quote_advancing_time_is_accepted(self):
        old = record(regularMarketTime=1792180800, marketCap=1e10)
        new = record(regularMarketTime=1792180801, marketCap=2e10)
        self.assertIs(build.merge({'quote': {'T': new}}, {'quote': {'T': old}})['quote']['T'], new)

    def test_yahoo_quote_adapter_rejects_undated_observations(self):
        class H:
            def crumb(self): return 'synthetic'
            def yahoo(self, _):
                return {'quoteResponse': {'result': [
                    {'symbol': 'GOOD', 'marketCap': 10., 'regularMarketTime': 1792180800},
                    {'symbol': 'BAD', 'marketCap': 10.}]}}
        self.assertEqual(set(quotes.yahoo_quotes(H(), ['GOOD', 'BAD'])), {'GOOD'})


class RatioObservationTests(unittest.TestCase):
    def test_same_day_current_values_remain_available(self):
        data, mk = complete_dataset()
        D, _, _ = build.assemble(data, mk, mk, NOW)
        self.assertIsNotNone(D['ratio'])
        self.assertEqual(D['ratio'].get('asOf'), D['meta']['asOf'])

    def test_same_month_different_days_are_unavailable(self):
        data, mk = complete_dataset()
        mk['ratio']['hl'] = monthly_record('2026-10-15', True)
        self.assertIsNone(build.assemble(data, mk, mk, NOW)[0]['ratio'])

    def test_new_receipts_do_not_make_old_values_current(self):
        data, mk = complete_dataset()
        mk['ratio'] = {'cyb': monthly_record('2026-10-01'), 'hl': monthly_record('2026-10-01', True)}
        self.assertIsNone(build.assemble(data, mk, mk, NOW)[0]['ratio'])

    def test_both_dates_must_match_page_date(self):
        data, mk = complete_dataset()
        mk['ratio'] = {'cyb': monthly_record('2026-10-15'), 'hl': monthly_record('2026-10-15', True)}
        self.assertIsNone(build.assemble(data, mk, mk, NOW)[0]['ratio'])

    def test_mixed_cached_and_fetched_dates_are_unavailable(self):
        data, cache = complete_dataset()
        cache['ratio']['hl'] = monthly_record('2026-10-15', True)
        fresh = copy.deepcopy(cache)
        fresh['ratio'].pop('hl')
        merged = build.merge(fresh, cache)
        self.assertIsNone(build.assemble(data, merged, fresh, NOW)[0]['ratio'])

    def test_same_day_cached_current_remains_available_within_receipt_window(self):
        data, cache = complete_dataset()
        fresh = copy.deepcopy(cache)
        fresh['ratio'].pop('hl')
        merged = build.merge(fresh, cache)
        self.assertIsNotNone(build.assemble(data, merged, fresh, NOW)[0]['ratio'])

    def test_expired_or_malformed_ratio_is_unavailable(self):
        for mutation in ('receipt', 'month', 'date'):
            with self.subTest(mutation=mutation):
                data, mk = complete_dataset()
                r = mk['ratio']['cyb']
                if mutation == 'receipt': r['receivedAt'] = (NOW-dt.timedelta(hours=37)).isoformat()
                if mutation == 'month': r['bars'][-1][0] = '2026-99'
                if mutation == 'date': r['asOf'] = '2026-10'
                self.assertIsNone(build.assemble(data, mk, mk, NOW)[0]['ratio'])

    def test_legacy_month_only_and_unproven_current_are_unavailable(self):
        for mutation in ('date', 'current', 'price'):
            with self.subTest(mutation=mutation):
                data, mk = complete_dataset()
                if mutation == 'date': mk['ratio']['cyb'].pop('asOf')
                if mutation == 'current': mk['ratio']['cyb'].pop('current')
                if mutation == 'price': mk['ratio']['cyb']['current']['close'] = 99.
                self.assertIsNone(build.assemble(data, mk, mk, NOW)[0]['ratio'])

    def test_ratio_regression_does_not_refresh_cached_receipt(self):
        old = monthly_record()
        old['receivedAt'] = (NOW-dt.timedelta(hours=2)).isoformat()
        for new in (monthly_record('2026-10-15'), record(bars=months(), src='tencent')):
            self.assertIs(build.merge({'ratio': {'cyb': new}}, {'ratio': {'cyb': old}})['ratio']['cyb'], old)

    def test_monthly_adapter_uses_daily_observation_not_month_bucket_date(self):
        class H:
            def json(self, url):
                if ',month,' in url:
                    return {'data': {'sz399006': {'month': [[m+'-01', '1', str(v)] for m, v in months()]}}}
                return {'data': {'sz399006': {'day': [['2026-10-15', '1', '101'], ['2026-10-16', '1', '102']]}}}
        r = quotes.monthly(H(), 'sz399006', '399006.SZ')
        self.assertEqual(r.get('asOf'), '2026-10-16')
        self.assertEqual(r.get('current'), {'date': '2026-10-16', 'close': 102., 'src': 'tencent'})
        self.assertEqual(r['bars'][-1], ['2026-10', 102.])
        self.assertEqual(r.get('periodDates', [])[-1], '2026-10-01')

    def test_monthly_adapter_does_not_invent_day_when_daily_fetch_fails(self):
        class H:
            def json(self, url):
                if ',month,' in url:
                    return {'data': {'sz399006': {'month': [[m+'-01', '1', str(v)] for m, v in months()]}}}
                raise RuntimeError('synthetic unavailable daily source')
        r = quotes.monthly(H(), 'sz399006', '399006.SZ')
        self.assertIsNone(r.get('asOf'))
        self.assertIsNone(r.get('current'))
        self.assertEqual(len(r['bars']), 121)

    def test_yahoo_month_bucket_timestamp_is_retained_but_not_used_as_observation(self):
        stamp = 1790812800
        class H:
            def json(self, _): raise RuntimeError('synthetic tencent failure')
            def yahoo(self, _):
                return {'chart': {'result': [{'meta': {'gmtoffset': 28800}, 'timestamp': [stamp],
                        'indicators': {'quote': [{'close': [100.]}]}}]}}
        r = quotes.monthly(H(), 'sz399006', '399006.SZ')
        self.assertEqual(r['periodTimestamps'], [stamp])
        self.assertIsNone(r['asOf'])
        self.assertIsNone(r['current'])


class FingerprintTests(unittest.TestCase):
    def test_only_collection_receipts_do_not_change_fingerprint_or_get_deleted(self):
        data, mk = complete_dataset()
        D = build.assemble(data, mk, mk, NOW)[0]
        changed = copy.deepcopy(D)
        def refresh(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == 'receivedAt': node[key] = (NOW+dt.timedelta(minutes=1)).isoformat()
                    else: refresh(value)
            elif isinstance(node, list):
                for value in node: refresh(value)
        refresh(changed)
        snapshot = copy.deepcopy(changed)
        self.assertEqual(build.fingerprint(D), build.fingerprint(changed))
        self.assertEqual(changed, snapshot)
        self.assertNotEqual(D['companies'][0]['provenance']['daily']['receivedAt'],
                            changed['companies'][0]['provenance']['daily']['receivedAt'])

    def test_material_price_date_validity_and_source_changes_change_fingerprint(self):
        data, mk = complete_dataset()
        D = build.assemble(data, mk, mk, NOW)[0]
        for section, key, value in ((None, 'price', 101.), ('daily', 'asOf', '2026-10-15'),
                                    ('daily', 'src', 'another-source'), ('valuation', 'status', 'missing'),
                                    ('financial', 'verified_at', '2026-10-15')):
            with self.subTest(section=section, key=key):
                changed = copy.deepcopy(D)
                target = changed['companies'][0] if section is None else changed['companies'][0]['provenance'][section]
                target[key] = value
                self.assertNotEqual(build.fingerprint(D), build.fingerprint(changed))

    def test_page_code_change_changes_fingerprint_without_touching_frozen_files(self):
        data, mk = complete_dataset()
        D = build.assemble(data, mk, mk, NOW)[0]
        with tempfile.TemporaryDirectory() as td, patch.object(build, 'RADAR', Path(td)):
            site = Path(td)/'site'
            site.mkdir()
            (site/'app.js').write_text('first', encoding='utf-8')
            before = build.fingerprint(D)
            (site/'app.js').write_text('second', encoding='utf-8')
            self.assertNotEqual(before, build.fingerprint(D))

    def test_receipt_expiry_changes_derived_validity_and_fingerprint(self):
        data, mk = complete_dataset()
        D = build.assemble(data, mk, mk, NOW)[0]
        expired = build.assemble(data, mk, mk, NOW+dt.timedelta(hours=37))[0]
        self.assertNotEqual(build.fingerprint(D), build.fingerprint(expired))
        self.assertTrue(expired['companies'][0]['stale'])
        self.assertIsNone(expired['ratio'])


class FrozenClock(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class CompleteMainTests(unittest.TestCase):
    def run_main(self, data, mk, root, force=False):
        args = ['build.py', '--cache', str(root/'cache.json'), '--out', str(root/'out'),
                '--audit-json', str(root/'audit.json')]
        if force: args.append('--force')
        with patch.object(sys, 'argv', args), patch.object(build.dt, 'datetime', FrozenClock), \
             patch.object(build, 'load_and_validate', return_value=(data, SimpleNamespace(errors=[], warnings=[]))), \
             patch.object(build, 'fetch_all', return_value=(mk, [])), \
             patch.object(build, 'gh_out') as output, patch.object(build, 'gh_summary'), \
             contextlib.redirect_stdout(io.StringIO()):
            code = build.main()
        return code, json.loads((root/'audit.json').read_text(encoding='utf-8')), output.call_args.kwargs

    def test_complete_successful_main_baseline(self):
        data, mk = complete_dataset()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            code, report, output = self.run_main(data, mk, root)
            self.assertEqual(code, 0)
            self.assertEqual(report['blockers'], [])
            self.assertEqual(output['changed'], 'true')
            self.assertTrue((root/'out/index.html').exists())
            self.assertEqual(len(report['data']['companies']), 42)
            self.assertEqual(len(report['data']['indices']), len(data['config']['indices']))
            self.assertIsNotNone(report['data']['ratio'])
            for c in report['data']['companies']:
                for key in ('price', 'mcapUSD', 'pe', 'revg', 'earng', 'gm'):
                    self.assertIsNotNone(c[key], (c['sym'], key))
                self.assertEqual(c['provenance']['financial']['status'], 'verified')

    def assert_gate(self, mutate, blocker):
        for force in (False, True):
            with self.subTest(force=force), tempfile.TemporaryDirectory() as td:
                data, mk = complete_dataset()
                mutate(data, mk)
                root = Path(td)
                code, report, output = self.run_main(data, mk, root, force)
                self.assertEqual(report['blockers'], [blocker])
                self.assertEqual(code, 3)
                self.assertEqual(output['changed'], 'false')
                self.assertFalse((root/'out').exists())

    def test_financial_gate_alone(self):
        self.assert_gate(lambda d, m: d['companies'][0].update(financial={}),
                         'financial_evidence_incomplete')

    def test_valuation_gate_alone(self):
        data, mk = complete_dataset()
        mk['quote'][data['companies'][0]['sym']]['marketCap'] = None
        D = build.assemble(data, mk, mk, NOW)[0]
        self.assertIsNone(D['companies'][0]['mcapUSD'])
        self.assertIn({'symbol': data['companies'][0]['sym'], 'kind': 'valuation', 'status': 'market_cap_unavailable'}, D['meta']['issues'])

    def test_close_gate_alone(self):
        self.assert_gate(lambda d, m: m['daily'][d['companies'][0]['sym']].update(phase='unknown'),
                         'unconfirmed_close_or_intraday_needs_label_approval')

    def test_date_gate_alone(self):
        self.assert_gate(lambda d, m: m['index'][d['config']['indices'][0]['symbol']].update(date='2026-10-15'),
                         'index_date_or_phase_needs_label_approval')

    def test_history_gate_alone(self):
        data, mk = complete_dataset()
        mk['daily'][data['companies'][0]['sym']]['bars'] = bars(54)
        D = build.assemble(data, mk, mk, NOW)[0]
        self.assertEqual(D['companies'][0]['history']['count'], 54)
        self.assertFalse(D['companies'][0]['history']['high52Available'])
        self.assertNotIn('short_price_history_fixed_chart_labels', D['meta']['blockers'])

    def test_repeated_fetch_saves_receipts_but_reports_unchanged(self):
        data, mk = complete_dataset()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(self.run_main(data, mk, root)[0], 0)
            for records in mk.values():
                for r in records.values(): r['receivedAt'] = (NOW-dt.timedelta(minutes=1)).isoformat()
            code, report, output = self.run_main(data, mk, root)
            self.assertEqual(code, 0)
            self.assertEqual(output['changed'], 'false')
            cache = json.loads((root/'cache.json').read_text(encoding='utf-8'))
            sym = data['companies'][0]['sym']
            self.assertEqual(cache['daily'][sym]['receivedAt'], mk['daily'][sym]['receivedAt'])
            self.assertEqual(report['data']['companies'][0]['provenance']['daily']['receivedAt'], mk['daily'][sym]['receivedAt'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
