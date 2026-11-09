"""Synthetic TWSE proof integration; no network or publishable market data."""
import copy
import datetime as dt
import os
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import acceptance_probe as probe
import build
import equity_close_proof as proof
import latest
import snapshot
from integrity import release_blockers
from test_acceptance_probe import Opener, Response
import test_pr5_calendar_release as holiday


NOW = dt.datetime.fromisoformat('2026-10-27T20:30:00+08:00')
DAY = '2026-10-27'
COMPANY = {'sym': '2383.TW', 'mkt': '台股', 'cur': 'TWD'}
EXECUTION = {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '12345', 'GITHUB_RUN_ATTEMPT': '1'}
TWSE_URL = 'https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=20261027&stockNo=2383&response=json'
YAHOO_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/2383.TW?range=5y&interval=1d&includeAdjustedClose=true'


def inputs(*, false_holidays=False):
    """Invent prices/history, retaining the real contradictory time-field shape."""
    record = holiday.synthetic_daily(COMPANY, NOW, DAY)
    record.update(returnBasis='yahoo-adjclose', phase='unknown')
    record['barTimestamps'] = {day: int(stamp) for day, stamp in record['barTimestamps'].items()}
    record['finality'].update(start=int(record['finality']['start']), end=int(record['finality']['end']))
    record['bars'][-1] = [DAY, 4750., 4750., 5200.]
    record['barTimestamps'][DAY] = record['finality']['end'] + 15
    if false_holidays:
        for day in ('2026-10-23', '2026-10-26'):
            record['bars'].append([day, 99999., 99999., 100000.])
            record['barTimestamps'][day] = int(dt.datetime.fromisoformat(day+'T09:00:00+08:00').timestamp())
        record['bars'].sort(key=lambda row: row[0])
    official = {'stat': 'OK', 'date': '20261027',
        'title': '115年10月 2383 台光電 各日成交資訊',
        'fields': ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價',
                   '收盤價', '漲跌價差', '成交筆數', '註記'],
        'data': [['115/10/27', '1,000', '4,750,000', '5,200.00', '5,200.00',
                  '4,685.00', '4,750.00', '-320.00', '100', '']], 'notes': [], 'total': 1}
    official_event = {'sourceUrl': TWSE_URL, 'httpStatus': 200,
                      'sha256': 'b' * 64, 'receivedAt': NOW.isoformat()}
    yahoo_event = {'sourceUrl': YAHOO_URL, 'httpStatus': 200,
                   'sha256': 'c' * 64, 'receivedAt': NOW.isoformat()}
    return record, official, official_event, yahoo_event


def enriched(*, false_holidays=False):
    record, official, official_event, yahoo_event = inputs(false_holidays=false_holidays)
    independent = proof.make_proof(record, official, official_event=official_event,
        yahoo_event=yahoo_event, expected_day=DAY, now=NOW, execution=EXECUTION)
    if not isinstance(independent, dict):
        raise AssertionError('synthetic independent evidence unexpectedly rejected')
    return record, {**record, 'independentCloseProof': independent}


def select(record, *, now=NOW, company=COMPANY):
    return latest.select_daily([company], {company['sym']: record}, now,
        calendar_policy=True, require_reviewed_close=True)


class TwseSelectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, EXECUTION)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_independent_proof_selects_day_without_rewriting_source_or_provider_rule(self):
        raw, record = enriched()
        before = copy.deepcopy(record)
        selected, status = select(record)
        self.assertFalse(snapshot.equity_bar_final(DAY, raw['barTimestamps'][DAY],
            raw['timezone'], raw['finality'], raw['receivedAt']))
        self.assertEqual(status['selectedCompanies'], 1)
        self.assertEqual(status['selectedDate'], DAY)
        self.assertEqual(selected['2383.TW']['phase'], 'closed')
        self.assertEqual(selected['2383.TW']['snapshotSelection']['sourcePhase'], 'unknown')
        self.assertEqual(selected['2383.TW']['bars'], raw['bars'])
        self.assertEqual(selected['2383.TW']['receivedAt'], raw['receivedAt'])
        self.assertEqual(selected['2383.TW']['barTimestamps'], raw['barTimestamps'])
        self.assertEqual(selected['2383.TW']['finality'], raw['finality'])
        self.assertEqual(record, before)
        self.assertEqual({k: v for k, v in record.items() if k != 'independentCloseProof'}, raw)

    def test_same_post_boundary_source_without_independent_proof_stays_blocked(self):
        raw, _ = enriched()
        self.assertEqual(select(raw)[0], {})
        self.assertEqual(select({**raw, 'independentCloseProof': {'verified': True}})[0], {})

    def test_metrics_keep_original_yahoo_values_and_adjustment_basis(self):
        raw, record = enriched()
        selected = select(record)[0]['2383.TW']
        before = copy.deepcopy(raw)
        expected = build.metrics(raw['bars'])
        actual = build.metrics(selected['bars'])
        self.assertEqual(actual, expected)
        self.assertEqual(actual['price'], 4750.)
        self.assertEqual(actual['r1d'], round(4750. / raw['bars'][-2][2] - 1, 5))
        self.assertEqual(selected['returnBasis'], 'yahoo-adjclose')
        self.assertEqual(raw, before)

    def test_independent_close_does_not_upgrade_a_later_quote(self):
        _, record = enriched()
        daily = select(record)[0]['2383.TW']
        quote = {'schemaVersion': 2, 'receivedAt': NOW.isoformat(), 'src': 'yahoo',
            'regularMarketTime': record['barTimestamps'][DAY], 'regularMarketPrice': 99999.,
            'marketState': 'POST', 'currency': 'TWD'}
        decision = latest.quote_after_completed_daily(quote, daily)
        self.assertFalse(decision['useQuote'])
        self.assertEqual(decision['reason'], 'completed_close_order_unproven')

    def test_reviewed_false_holidays_still_removed_from_selected_history(self):
        raw, record = enriched(false_holidays=True)
        before = copy.deepcopy(record)
        selected = select(record)[0]['2383.TW']
        self.assertEqual(selected['asOf'], DAY)
        dates = [row[0] for row in selected['bars']]
        self.assertNotIn('2026-10-23', dates)
        self.assertNotIn('2026-10-26', dates)
        self.assertNotIn(99999., [row[1] for row in selected['bars']])
        self.assertIn('2026-10-23', [row[0] for row in raw['bars']])
        self.assertEqual(record, before)

    def test_bound_input_changes_are_rejected_by_all_selector_layers(self):
        _, source = enriched()
        for change in ({'currency': 'USD'}, {'asOf': '2026-10-22'},
                       {'receivedAt': '2026-10-27T12:00:00+08:00'},
                       {'receivedAt': '2026-10-28T20:30:00+08:00'},
                       {'timezone': 'UTC'}):
            with self.subTest(change=change):
                record = copy.deepcopy(source)
                record.update(change)
                self.assertEqual(select(record)[0], {})
        record = copy.deepcopy(source)
        record['bars'][-1][2] = 4749.
        self.assertEqual(select(record)[0], {})

    def test_evidence_cannot_cross_symbol_or_execution(self):
        _, record = enriched()
        other = {'sym': '2330.TW', 'mkt': '台股', 'cur': 'TWD'}
        self.assertEqual(select(record, company=other)[0], {})
        for changed in ({'GITHUB_RUN_ID': '12346'}, {'GITHUB_SHA': 'd' * 40},
                        {'GITHUB_RUN_ATTEMPT': '2'}):
            with self.subTest(changed=changed), patch.dict(os.environ, changed):
                self.assertEqual(select(record)[0], {})

    def test_expired_evidence_is_not_refreshed_by_advancing_clock(self):
        _, record = enriched()
        before = copy.deepcopy(record)
        self.assertEqual(select(record, now=NOW+dt.timedelta(hours=37))[0], {})
        self.assertEqual(record, before)


class TwseTransportIntegrationTests(unittest.TestCase):
    def test_only_exact_twse_route_and_scope_is_allowed(self):
        self.assertEqual(probe.route(TWSE_URL), ('twse-close', 'stock-day'))
        for invalid in (TWSE_URL.replace('https:', 'http:'),
                        TWSE_URL.replace('www.twse.com.tw', 'example.test'),
                        TWSE_URL.replace('stockNo=2383', 'stockNo=2330'),
                        TWSE_URL.replace('response=json', 'response=csv'),
                        TWSE_URL.replace('20261027', '20260230'),
                        TWSE_URL+'&date=20261027', TWSE_URL+'&extra=1',
                        TWSE_URL+'&stockNo=', TWSE_URL+'#fragment',
                        TWSE_URL.replace('/STOCK_DAY?', '/MI_INDEX?')):
            with self.subTest(invalid=invalid), self.assertRaises(probe.StopProbe):
                probe.route(invalid)

    def test_twse_transport_uses_existing_240_limit_and_bounded_retry(self):
        self.assertEqual(probe.MAX_REQUESTS, 240)
        budget = probe.Budget()
        budget.count = 238
        client = probe.ProbeHttp(budget, 'twse')
        client.op = Opener(urllib.error.HTTPError(TWSE_URL, 429, 'ignored',
            {'Retry-After': '0'}, None), Response(b'{}'))
        with patch.object(probe.time, 'sleep'):
            self.assertEqual(client.json(TWSE_URL), {})
        self.assertEqual(client.op.calls, 2)
        self.assertEqual(budget.count, 240)
        with self.assertRaises(probe.StopProbe):
            client.get(TWSE_URL)
        self.assertEqual(client.op.calls, 2)

    def test_twse_denials_stop_lane_and_redirects_are_not_followed(self):
        for code in (401, 403, 451):
            with self.subTest(code=code):
                budget = probe.Budget()
                client = probe.ProbeHttp(budget, 'twse')
                client.op = Opener(urllib.error.HTTPError(TWSE_URL, code, 'ignored', {}, None))
                with self.assertRaises(probe.StopProbe):
                    client.get(TWSE_URL)
                with self.assertRaises(probe.StopProbe):
                    client.get(TWSE_URL)
                self.assertEqual(client.op.calls, 1)
                self.assertEqual(budget.count, 1)
        with self.assertRaises(probe.StopProbe):
            probe.NoRedirect().redirect_request(None, None, 302, '', {}, TWSE_URL)


class TwseFullAssemblyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        holiday.FullHolidayReleaseTests.setUpClass()
        cls.data = holiday.FullHolidayReleaseTests.data
        cls.research = holiday.FullHolidayReleaseTests.research

    def test_full_synthetic_42_company_packet_uses_proven_close_without_publication(self):
        with patch.dict(os.environ, EXECUTION):
            raw, record = enriched(false_holidays=True)
            market = holiday.synthetic_market(self.data, NOW)
            market['daily']['2383.TW'] = record
            market['quote']['2383.TW'].update(regularMarketTime=raw['barTimestamps'][DAY],
                regularMarketPrice=99999., marketState='POST')
            before = copy.deepcopy(market)
            result, stale, missing = build.assemble_notion(
                self.research, self.data, market, market, NOW)
            result['meta']['fixture'] = True
            self.assertEqual(len(result['companies']), 42)
            self.assertEqual(len(result['indices']), 8)
            self.assertEqual(stale, [])
            self.assertEqual(missing, [])
            self.assertEqual(release_blockers(result), ['synthetic_fixture_not_publishable'])
            row = next(c for c in result['companies'] if c['sym'] == '2383.TW')
            self.assertEqual(row['price'], 4750.)
            self.assertEqual(row['priceAsOf'], DAY)
            self.assertEqual(row['metricAsOf'], DAY)
            self.assertEqual(row['pricePhase'], 'closed')
            self.assertFalse(row['priceSelection']['useQuote'])
            self.assertEqual(row['provenance']['daily']['receivedAt'], raw['receivedAt'])
            self.assertEqual(row['provenance']['daily']['snapshotSelection']['sourcePhase'], 'unknown')
            self.assertNotIn(99999., row['sc'])
            self.assertEqual(market, before)


if __name__ == '__main__':
    unittest.main()
