"""Synthetic regression for run 39884209603's 09:29 pre-open failure.

The historical artifact retained selected DATA and receipts, not the raw chart
or market cache. These synthetic provider boundaries are NOT a reconstructed
historical payload and never authorize publication.
"""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

from test_integrity import build, quotes, financial_evidence
from test_completed_snapshot import epoch
from snapshot import completed_bars

DAY = '2026-10-23'
PREVIOUS = '2026-10-22'
ZONE = 'Asia/Hong_Kong'
RECEIVED = '2026-10-23T01:29:55.853766+00:00'
CLOCK = dt.datetime.fromisoformat('2026-10-23T09:31:01.249772+08:00')


def document():
    return {'chart': {'result': [{
        'meta': {'currency': 'HKD', 'exchangeTimezoneName': ZONE,
                 'currentTradingPeriod': {'regular': {
                     'start': epoch(DAY, ZONE, 9) + 30 * 60,
                     'end': epoch(DAY, ZONE, 16)}}},
        'timestamp': [epoch(PREVIOUS, ZONE, 9) + 30 * 60,
                      epoch(DAY, ZONE, 9) + 29 * 60],
        'indicators': {'quote': [{'close': [100., 999.], 'high': [110., 1000.]}],
                       'adjclose': [{'adjclose': [100., 999.]}]},
    }]}}


def parse(doc=None, received=RECEIVED):
    doc = document() if doc is None else doc

    class Http:
        def yahoo(self, _):
            return copy.deepcopy(doc)

    with patch.object(quotes, 'stamp', side_effect=lambda **kw: dict(
            kw, schemaVersion=2, receivedAt=received)):
        return quotes.yahoo_daily(Http(), '0522.HK')


class PreopenDailyTests(unittest.TestCase):
    def setUp(self):
        network = patch('socket.socket', side_effect=AssertionError('Offline only'))
        network.start()
        self.addCleanup(network.stop)

    def test_provider_preopen_bar_preserves_only_proven_previous_close(self):
        record = parse()
        before = copy.deepcopy(record)
        self.assertEqual(record['phase'], 'preopen')
        self.assertEqual(completed_bars(record), [[PREVIOUS, 100., 100., 110.]])
        self.assertEqual(record, before)
        selected, meta = build.latest.select_daily(
            [{'sym': '0522.HK', 'mkt': '港股', 'cur': 'HKD'}],
            {'0522.HK': record}, CLOCK)
        self.assertEqual(meta['selectedDate'], PREVIOUS)
        self.assertEqual(selected['0522.HK']['phase'], 'closed')
        self.assertEqual(selected['0522.HK']['receivedAt'], RECEIVED)
        self.assertEqual(selected['0522.HK']['snapshotSelection']['sourcePhase'], 'preopen')
        self.assertNotIn(999., [bar[1] for bar in selected['0522.HK']['bars']])

    def test_waiting_cannot_turn_cached_preopen_price_into_close(self):
        record = parse()
        selected, _ = build.latest.select_daily(
            [{'sym': '0522.HK', 'mkt': '港股', 'cur': 'HKD'}],
            {'0522.HK': record}, CLOCK + dt.timedelta(hours=8))
        self.assertEqual(selected['0522.HK']['asOf'], PREVIOUS)
        self.assertEqual(selected['0522.HK']['receivedAt'], RECEIVED)

    def test_unknown_and_invalid_preopen_proof_still_have_no_completed_history(self):
        record = parse()
        for change in ({'phase': 'unknown'}, {'finality': {}},
                       {'timezone': 'bad-zone'}, {'barTimestamps': {}}, {'barTimestamps': ['bad']},
                       {'receivedAt': '2026-10-23'}, {'schemaVersion': 1},
                       {'finality': {'method': 'guessed', 'start': 1, 'end': 2}},
                       {'receivedAt': '2026-10-23T01:31:00+00:00'}):
            with self.subTest(change=change):
                self.assertEqual(completed_bars({**record, **change}), [])

    def test_preopen_is_not_inferred_without_valid_same_day_provider_session(self):
        for regular in ({}, {'start': None, 'end': None},
                        {'start': epoch(DAY, ZONE, 17), 'end': epoch(DAY, ZONE, 16)},
                        {'start': epoch('2026-10-26', ZONE, 9),
                         'end': epoch('2026-10-26', ZONE, 16)}):
            with self.subTest(regular=regular):
                doc = document()
                doc['chart']['result'][0]['meta']['currentTradingPeriod']['regular'] = regular
                record = parse(doc)
                self.assertEqual(record['phase'], 'unknown')
                self.assertEqual(completed_bars(record), [])

    def test_preopen_does_not_authorize_today_only_or_future_bar(self):
        doc = document()
        row = doc['chart']['result'][0]
        row['timestamp'] = row['timestamp'][1:]
        row['indicators']['quote'][0] = {'close': [999.], 'high': [1000.]}
        row['indicators']['adjclose'][0]['adjclose'] = [999.]
        self.assertEqual(completed_bars(parse(doc)), [])
        row['timestamp'][0] = epoch(DAY, ZONE, 10)
        self.assertEqual(parse(doc)['phase'], 'unknown')
        self.assertEqual(completed_bars(parse(doc)), [])

    def test_yahoo_preopen_index_remains_unknown_and_partial_through_coverage(self):
        class Http:
            def yahoo(self, _):
                return document()

        with patch.object(quotes, 'stamp', side_effect=lambda **kw: dict(
                kw, schemaVersion=2, receivedAt=RECEIVED)):
            index = quotes.index_quote(Http(), '^HSI', source='yahoo')
        self.assertEqual(index['dailyHistory']['phase'], 'preopen')
        self.assertEqual(index['phase'], 'unknown')
        self.assertEqual(index['price'], 999.)
        self.assertEqual(index['date'], DAY)
        data, validation = build.load_and_validate(build.RADAR, build.REPO, CLOCK.date())
        self.assertFalse(validation.errors)
        data['companies'] = [company for company in data['companies'] if company['sym'] == '0522.HK']
        data['companies'][0]['financial'] = financial_evidence()
        data['config']['indices'] = [{'symbol': '^HSI', 'name': '恒生指数'}]
        market = {key: {} for key in ('daily', 'quote', 'index', 'fx', 'ratio')}
        market['daily']['0522.HK'] = parse()
        market['index']['^HSI'] = index
        assembled = build.assemble(data, market, market, CLOCK)[0]
        self.assertEqual(assembled['indices'][0]['phase'], 'unknown')
        self.assertEqual(assembled['indices'][0]['price'], 999.)
        coverage = next(row for row in assembled['meta']['coverage']
                        if row['kind'] == 'index' and row['symbol'] == '^HSI')
        self.assertEqual(coverage['status'], 'partial')
        self.assertEqual(coverage['reason'], 'phase_unknown')

    def test_fixed_clock_assembly_uses_completed_history_without_weakening_gates(self):
        data, validation = build.load_and_validate(build.RADAR, build.REPO, CLOCK.date())
        self.assertFalse(validation.errors)
        data['companies'] = [company for company in data['companies'] if company['sym'] == '0522.HK']
        company = data['companies'][0]
        company['financial'] = financial_evidence()
        data['config']['indices'] = []
        market = {key: {} for key in ('daily', 'quote', 'index', 'fx', 'ratio')}
        market['daily']['0522.HK'] = parse()
        before = copy.deepcopy(market)
        assembled, stale, missing = build.assemble(data, market, market, CLOCK)
        self.assertFalse(stale)
        self.assertFalse(missing)
        self.assertEqual(build.release_blockers(assembled), [])
        self.assertEqual(assembled['companies'][0]['price'], 100.)
        self.assertEqual(assembled['companies'][0]['metricAsOf'], PREVIOUS)
        self.assertEqual(market, before)
        # Missing proof and stale receipts still fail closed; no date refreshing.
        for change in ({'finality': {}}, {'receivedAt': '2026-10-20T01:29:55+00:00'}):
            with self.subTest(change=change):
                market['daily']['0522.HK'] = {**parse(), **change}
                blocked = build.assemble(data, market, market, CLOCK)[0]
                self.assertTrue(build.release_blockers(blocked))


if __name__ == '__main__':
    unittest.main()
