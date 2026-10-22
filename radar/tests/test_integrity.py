"""Synthetic regression tests: no live market access and no trading."""
import copy
import contextlib
import datetime as dt
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar' / 'scripts'))
import build
import quotes
from integrity import fresh_record, financial_status, release_blockers

NOW = dt.datetime(2026, 10, 18, 10, tzinfo=build.BJ)


def record(**kw):
    return dict(schemaVersion=2, receivedAt=NOW.isoformat(), **kw)


def historical_fx(currency='CNY', rates=None, **overrides):
    """Synthetic confirmed daily series, with actual provider-proof field shapes."""
    rates = rates or [['2026-10-16', 7., 1/7 if currency == 'EUR' else 7.]]
    start = dt.datetime(2026, 10, 16, tzinfo=dt.UTC).timestamp()
    value = record(value=rates[-1][1], asOf=rates[-1][0], src='yahoo', currency=currency,
        direction='USD-to-local', priceBasis='daily-close', timezone='UTC', rates=rates,
        rateTimestamps={r[0]:dt.datetime.fromisoformat(r[0]).replace(tzinfo=dt.UTC).timestamp() for r in rates},
        finality={'method':'provider-session-boundary','start':start,'end':start+86400})
    value.update(overrides)
    return value


def financial_evidence():
    return dict(source_name='Synthetic filing', source_url='https://example.test/report',
        source_urls=['https://example.test/report'], period_end='2026-06-30',
        published_at='2026-08-01', verified_at='2026-10-16', basis='single_quarter',
        currency='USD', accounting_basis='US GAAP', fiscal_year='FY2026', fiscal_period='Q2',
        profit_metric='net_income', revenue_scope='consolidated', profit_scope='parent',
        margin_scope='consolidated', report_status='final', profit_comparison='comparable',
        derivation='reported', review_note='Synthetic offline test only')


def bars(count=800):
    end = dt.date(2026, 10, 16)
    return [[(end-dt.timedelta(days=count-i-1)).isoformat(), 100., 100., 110.] for i in range(count)]


def months(count=121, current=True):
    last = 2026*12+9-(not current)
    return [[f'{n//12:04}-{n%12+1:02}', 100.+i] for i, n in enumerate(range(last-count+1, last+1))]


def dataset():
    data, report = build.load_and_validate(build.RADAR, ROOT, NOW.date())
    assert not report.errors
    mk = {k: {} for k in ('daily', 'quote', 'index', 'fx', 'ratio')}
    return data, mk


class MetricTests(unittest.TestCase):
    def test_split_return_uses_adjusted_but_drawdown_uses_displayed_raw_high(self):
        b = bars()
        b[-2][1:4] = [200., 100., 210.]
        b[-1][1:4] = [100., 100., 110.]
        m = build.metrics(b)
        self.assertEqual(m['r1d'], 0)
        self.assertEqual(m['hi52'], 210)
        self.assertEqual(m['dd52'], round(100/210-1, 4))

    def test_dividend_adjusted_return(self):
        b = bars(2)
        b[0][1:3] = [100., 98.]
        b[1][1:3] = [98., 98.]
        self.assertEqual(build.metrics(b)['r1d'], 0)

    def test_52_weeks_is_calendar_not_252_observations(self):
        b = bars()
        b[-300][3] = 250.
        b[-365][3] = 900.
        self.assertEqual(build.metrics(b)['hi52'], 250)

    def test_short_history_does_not_claim_52_week_high(self):
        m = build.metrics(bars(100))
        self.assertIsNone(m['hi52'])
        self.assertIsNone(m['dd52'])

    def test_missing_adjustment_stays_missing(self):
        b = bars()
        b[-1][2] = None
        m = build.metrics(b)
        for k in ('r1d', 'r5', 'r20', 'r60', 'ytd'):
            self.assertIsNone(m[k])
        self.assertEqual(m['price'], 100)

    def test_missing_high_not_filled_by_close(self):
        b = bars()
        b[-2][3] = None
        self.assertIsNone(build.metrics(b)['hi52'])

    def test_bad_bars_rejected(self):
        for value in (float('nan'), float('inf'), 0, -1):
            b = bars(2)
            b[-1][1] = value
            self.assertEqual(build.metrics(b), {})
        b = bars(2)
        b[-1][0] = b[0][0]
        self.assertEqual(build.metrics(b), {})


class FakeHttp:
    def __init__(self, raw, adj=None):
        self.raw, self.adj, self.urls = raw, adj, []
    def json(self, url):
        self.urls.append(url)
        return {'data': {'sh600000': {'qfqday': self.adj} if url.endswith(',qfq') else {'day': self.raw}}}


class ProviderTests(unittest.TestCase):
    def test_tencent_join_by_date_and_never_copy_raw_into_adjusted(self):
        h = FakeHttp([['2026-10-15', '99', '100', '101'], ['2026-10-16', '49', '50', '51']],
                     [['2026-10-16', '49', '50'], ['2026-10-15', '49', '50']])
        d = quotes.tencent_daily(h, '600000.SS')
        self.assertEqual(d['bars'][0], ['2026-10-15', 100, 50, 101])
        self.assertEqual(build.metrics(d['bars'])['r1d'], 0)
        self.assertEqual(len(h.urls), 2)
        self.assertEqual(d['returnBasis'], 'tencent-qfq')

    def test_tencent_no_qfq(self):
        h = FakeHttp([['2026-10-16', '49', '50', '51']], [])
        self.assertIsNone(quotes.tencent_daily(h, '600000.SS')['bars'][0][2])

    def test_yahoo_no_adjustment_no_realtime_splice(self):
        payload = {'chart': {'result': [{'meta': {'exchangeTimezoneName': 'America/New_York',
                    'regularMarketPrice': 999, 'regularMarketTime': 1792267200},
                    'timestamp': [1792177200], 'indicators': {'quote': [{'close': [100], 'high': [110]}]}}]}}
        class H:
            def yahoo(self, path): return payload
        d = quotes.yahoo_daily(H(), 'TEST')
        self.assertEqual(len(d['bars']), 1)
        self.assertEqual(d['bars'][0][1:], [100, None, 110])

    def test_exchange_date_handles_dst(self):
        timestamp = dt.datetime(2026, 1, 2, 4, 30, tzinfo=dt.UTC).timestamp()
        self.assertEqual(quotes.exchange_date(timestamp, {'exchangeTimezoneName': 'America/New_York', 'gmtoffset': -14400}), '2026-01-01')


class MonthTests(unittest.TestCase):
    def test_complete_last_month_is_included(self):
        c = months(120, False)
        h = [[m, 100] for m, _ in c]
        r = build.ratio_block(c, h, NOW.date())
        self.assertEqual(r['completedMonths'], 120)
        self.assertEqual(r['n120'], 119)
        self.assertFalse(r['uiCompatible'])

    def test_current_month_is_excluded(self):
        c = months()
        h = [[m, 100] for m, _ in c]
        r = build.ratio_block(c, h, NOW.date())
        self.assertEqual(r['completedMonths'], 120)
        self.assertEqual(r['n120'], 120)
        self.assertTrue(r['uiCompatible'])

    def test_short_empty_gapped_zero_histories(self):
        for c in ([], months(12), months()[:40]+months()[41:]):
            self.assertIsNone(build.ratio_block(c, [[m, 100] for m, _ in c], NOW.date()))
        c = months()
        self.assertIsNone(build.ratio_block(c, [[m, 0] for m, _ in c], NOW.date()))


class CacheAndContractTests(unittest.TestCase):
    def test_regressing_provider_does_not_refresh_cache_receipt(self):
        data, mk = dataset()
        s = data['companies'][0]['sym']
        mk['daily'][s] = record(bars=bars(), priceBasis='raw', asOf='2026-10-16', phase='closed')
        fresh = {k: {} for k in mk}
        fresh['daily'][s] = record(bars=bars()[:-1], priceBasis='raw', asOf='2026-10-15', phase='closed')
        merged = build.merge(fresh, mk)
        self.assertEqual(merged['daily'][s]['asOf'], '2026-10-16')
        _, stale, _ = build.assemble(data, merged, fresh, NOW)
        self.assertEqual(len(stale), 1)

    def test_stale_indices_and_fx_not_exposed(self):
        data, mk = dataset()
        mk['fx']['CNY'] = record(value=7, asOf='2025-01-01', src='yahoo')
        mk['index'][data['config']['indices'][0]['symbol']] = record(price=3000, chg=.1, date='2025-01-01')
        D, _, _ = build.assemble(data, mk, mk, NOW)
        self.assertEqual(D['indices'], [])
        self.assertNotIn('CNY', D['meta']['fx'])

    def test_valid_evidence_preserves_values_and_negative_pe_is_missing(self):
        data, mk = dataset()
        c = data['companies'][1]  # USD company
        c['financial'] = financial_evidence()
        mk['daily'][c['sym']] = record(bars=bars(), priceBasis='raw', asOf='2026-10-16', phase='closed')
        mk['quote'][c['sym']] = record(marketCap=1e10, trailingPE=-3, currency='USD', src='yahoo', marketState='CLOSED',
            regularMarketTime=dt.datetime(2026,10,16,20,tzinfo=dt.UTC).timestamp())
        D, _, _ = build.assemble(data, mk, mk, NOW)
        self.assertEqual(D['companies'][1]['revg'], c['revg'])
        self.assertEqual(D['companies'][1]['mcapUSD'], 100)
        self.assertIsNone(D['companies'][1]['pe'])

    def test_legacy_cache_not_accepted(self):
        self.assertFalse(fresh_record({'receivedAt': NOW.isoformat()}, NOW))
        data, mk = dataset()
        mk['daily'][data['companies'][0]['sym']] = {'bars': bars()}
        D, _, missing = build.assemble(data, mk, mk, NOW)
        self.assertEqual(len(missing), 42)
        self.assertIsNone(D['meta']['asOf'])

    def test_received_and_observation_ages_both_checked(self):
        self.assertTrue(fresh_record(record(), NOW, '2026-10-16', '美股'))
        self.assertFalse(fresh_record(record(), NOW, '2026-09-30', '美股'))
        self.assertFalse(fresh_record({'schemaVersion': 2, 'receivedAt': '2026-10-12T12:00:00+08:00'}, NOW, '2026-10-16'))
        self.assertFalse(fresh_record(record(), NOW, '2026-10-19'))

    def test_offline_and_successful_but_old_response_are_stale(self):
        data, mk = dataset()
        s = data['companies'][0]['sym']
        b = bars()
        mk['daily'][s] = record(bars=b, priceBasis='raw', asOf=b[-1][0], phase='closed')
        fresh = {**mk, 'daily': {}, 'offline': True}
        D, stale, _ = build.assemble(data, mk, fresh, NOW)
        self.assertEqual(len(stale), 1)
        self.assertTrue(D['companies'][0]['stale'])
        self.assertIn('offline_not_publishable', release_blockers(D))
        old = NOW + dt.timedelta(days=10)
        D, stale, _ = build.assemble(data, mk, mk, old)
        self.assertEqual(len(stale), 1)

    def test_market_dates_remain_separate_from_generated_at(self):
        data, mk = dataset()
        for c in data['companies'][:2]:
            b = bars()
            if c['mkt'] == '美股': b = b[:-1]
            mk['daily'][c['sym']] = record(bars=b, priceBasis='raw', asOf=b[-1][0], phase='closed')
        D, _, _ = build.assemble(data, mk, mk, NOW)
        self.assertEqual(D['meta']['asOfByMarket']['A股'], ['2026-10-16'])
        self.assertEqual(D['meta']['asOfByMarket']['美股'], ['2026-10-15'])
        self.assertEqual(D['meta']['snapshot']['sourceAsOfByMarket']['A股'], ['2026-10-16'])
        self.assertIn('mixed_or_missing_market_dates_need_label_approval', release_blockers(D))
        self.assertTrue(D['meta']['generatedAt'].startswith('2026-10-18'))

    def test_financial_and_valuation_fallbacks_not_used(self):
        data, mk = dataset()
        for c in data['companies']: c['financial'] = {}
        D, _, _ = build.assemble(data, mk, mk, NOW)
        self.assertEqual([len(D[k]) for k in ('industries','chokepoints','companies')], [15,16,42])
        for c in D['companies']:
            for k in ('revg','earng','gm','pe','mcapUSD'):
                self.assertIsNone(c[k])
        json.dumps(D, allow_nan=False)

    def test_provider_high_does_not_override_metric_high(self):
        data, mk = dataset()
        s = data['companies'][0]['sym']
        mk['daily'][s] = record(bars=bars(), priceBasis='raw', asOf='2026-10-16', phase='closed', hi52=999)
        D, _, _ = build.assemble(data, mk, mk, NOW)
        self.assertEqual(D['companies'][0]['hi52'], 110)

    def test_schedule_gap_recorded_without_changing_schedule(self):
        workflow = (ROOT/'.github/workflows/radar-deploy.yml.disabled').read_text(encoding='utf-8')
        self.assertIn('5 23 * * 0-4', workflow)
        friday_utc = dt.datetime(2026, 10, 16, 23, 5, tzinfo=dt.UTC)
        self.assertEqual(friday_utc.astimezone(build.BJ).weekday(), 5)
        self.assertNotIn(5, range(0,5))  # cron weekday Friday = 5, currently absent

    def test_only_authorized_workflows_are_active(self):
        workflows = ROOT/'.github/workflows'
        self.assertEqual(sorted(p.name for p in workflows.glob('*.yml')),
                         ['radar-interface-acceptance.yml', 'radar-offline.yml', 'radar-production.yml'])
        self.assertEqual(list(workflows.glob('*.yaml')), [])
        for name in ('radar-deploy', 'radar-preview'):
            original = subprocess.check_output([
                'git', 'show', f'22d9601:.github/workflows/{name}.yml'], cwd=ROOT)
            self.assertEqual((workflows/f'{name}.yml.disabled').read_bytes(), original)

    def test_offline_pr_ci_has_no_secret_or_publication_capability(self):
        workflow = json.loads((ROOT/'.github/workflows/radar-offline.yml').read_text())
        self.assertEqual(workflow['on'], {'pull_request': {'branches': ['fix/radar-truthfulness-2026-10-18']}})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(set(workflow['jobs']), {'offline'})
        job = workflow['jobs']['offline']
        self.assertEqual(job['if'], "github.repository == 'lwd619783-byte/research-radar'")
        self.assertNotIn('secrets.', json.dumps(workflow))
        self.assertNotIn('permissions', job)
        self.assertEqual([s['run'] for s in job['steps'] if 'run' in s],
                         ['python -B radar/scripts/acceptance_probe.py --preflight'])
        checkout = next(s for s in job['steps'] if 'actions/checkout@' in s.get('uses', ''))
        self.assertFalse(checkout['with']['persist-credentials'])

    def test_force_does_not_bypass_missing_data_gate(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run([sys.executable, str(ROOT/'radar/scripts/build.py'), '--offline', '--force',
                                   '--cache', str(Path(td)/'none.json'), '--out', str(Path(td)/'out'),
                                   '--audit-json', str(Path(td)/'report.json')], capture_output=True)
            self.assertEqual(proc.returncode, 2)
            self.assertFalse((Path(td)/'out/index.html').exists())


class EvidenceTests(unittest.TestCase):
    def test_financial_metadata(self):
        fin = financial_evidence()
        self.assertEqual(financial_status(fin, NOW.date()), 'verified')
        self.assertEqual(financial_status({}, NOW.date()), 'missing_source')
        fin['published_at'] = '2027-01-01'
        self.assertEqual(financial_status(fin, NOW.date()), 'invalid_dates')


if __name__ == '__main__':
    unittest.main(verbosity=2)
