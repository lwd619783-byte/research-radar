"""Synthetic European opening-session regressions; no historical payload claim.

Public observations on 2026-10-23 showed a null previous-day close alongside a
current intraday bar. These isolated inputs exercise the real parser, completed
bar proof and strict calendar selector without replacing any of their gates.
"""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import latest
import market_calendar
import quotes
from integrity import fresh_record
from snapshot import completed_bars


CLOCK = dt.datetime.fromisoformat('2026-10-23T07:32:00+00:00')
DAY = '2026-10-23'
PREVIOUS = '2026-10-22'
OLDER = '2026-10-21'
MARKETS = (('ENR.DE', 'Europe/Berlin'), ('SU.PA', 'Europe/Paris'))


def epoch(day, zone, hour=9, minute=0):
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hour, minute),
                               ZoneInfo(zone)).timestamp()


def document(zone, previous_close=None):
    return {'chart': {'result': [{
        'meta': {'currency': 'EUR', 'exchangeTimezoneName': zone,
                 'currentTradingPeriod': {'regular': {
                     'start': epoch(DAY, zone), 'end': epoch(DAY, zone, 17, 30)}}},
        'timestamp': [epoch(day, zone) for day in (OLDER, PREVIOUS, DAY)],
        'indicators': {
            'quote': [{'close': [100., previous_close, 999.],
                       'high': [110., 120. if previous_close else None, 1000.]}],
            'adjclose': [{'adjclose': [100., previous_close, 999.]}]},
    }]}}


def parse(symbol, doc, received=CLOCK):
    class Http:
        def yahoo(self, path):
            return copy.deepcopy(doc)

    # Only the transport and acquisition clock are synthetic; finality and
    # freshness are the production implementations.
    with patch.object(quotes, 'stamp', side_effect=lambda **kw: dict(
            kw, schemaVersion=2, receivedAt=received.isoformat())):
        return quotes.yahoo_daily(Http(), symbol)


def select(symbol, record, now=CLOCK):
    return latest.select_daily([{'sym': symbol, 'mkt': '欧股', 'cur': 'EUR'}],
                               {symbol: record}, now, calendar_policy=True)


class EuropeMissingCloseTests(unittest.TestCase):
    def setUp(self):
        network = patch('socket.socket', side_effect=AssertionError('Offline only'))
        network.start()
        self.addCleanup(network.stop)

    def test_null_previous_close_is_removed_and_older_close_is_rejected(self):
        for symbol, zone in MARKETS:
            with self.subTest(symbol=symbol):
                doc = document(zone)
                before_doc = copy.deepcopy(doc)
                record = parse(symbol, doc)
                before_record = copy.deepcopy(record)
                self.assertEqual(record['asOf'], DAY)
                self.assertEqual(record['phase'], 'intraday')
                self.assertEqual([bar[0] for bar in record['bars']], [OLDER, DAY])
                self.assertNotIn(PREVIOUS, record['barTimestamps'])
                self.assertEqual([bar[0] for bar in completed_bars(record)], [OLDER])
                self.assertEqual(market_calendar.context(symbol, CLOCK)['expectedCompletedDate'], PREVIOUS)
                chosen, meta = select(symbol, record)
                self.assertEqual(chosen, {})
                self.assertEqual(meta['status'], 'incomplete')
                self.assertEqual(meta['selectedCompanies'], 0)
                self.assertFalse(fresh_record(record, CLOCK, OLDER, '欧股', symbol=symbol))
                self.assertEqual(doc, before_doc)
                self.assertEqual(record, before_record)

    def test_real_previous_close_is_selected_without_promoting_today(self):
        for symbol, zone in MARKETS:
            with self.subTest(symbol=symbol):
                record = parse(symbol, document(zone, previous_close=115.))
                before = copy.deepcopy(record)
                chosen, meta = select(symbol, record)
                selected = chosen[symbol]
                self.assertEqual(meta['status'], 'complete')
                self.assertEqual(selected['asOf'], PREVIOUS)
                self.assertEqual(selected['phase'], 'closed')
                self.assertEqual(selected['bars'], [[OLDER, 100., 100., 110.],
                                                     [PREVIOUS, 115., 115., 120.]])
                self.assertEqual(selected['snapshotSelection']['sourceAsOf'], DAY)
                self.assertEqual(selected['snapshotSelection']['sourcePhase'], 'intraday')
                self.assertEqual(selected['receivedAt'], record['receivedAt'])
                self.assertEqual(record, before)

    def test_waiting_past_close_does_not_finalize_a_cached_intraday_bar(self):
        later = CLOCK.replace(hour=16)
        for symbol, zone in MARKETS:
            for previous_close in (None, 115.):
                with self.subTest(symbol=symbol, previous_close=previous_close):
                    record = parse(symbol, document(zone, previous_close))
                    before = copy.deepcopy(record)
                    expected_last = PREVIOUS if previous_close else OLDER
                    self.assertEqual(completed_bars(record)[-1][0], expected_last)
                    self.assertEqual(market_calendar.context(symbol, later)['expectedCompletedDate'], DAY)
                    self.assertEqual(select(symbol, record, later)[0], {})
                    self.assertEqual(completed_bars(record)[-1][0], expected_last)
                    self.assertEqual(record['receivedAt'], CLOCK.isoformat())
                    self.assertEqual(record, before)

    def test_new_receipt_without_missing_close_does_not_fill_the_gap(self):
        later = CLOCK + dt.timedelta(minutes=30)
        for symbol, zone in MARKETS:
            with self.subTest(symbol=symbol):
                original = parse(symbol, document(zone))
                newly_observed = parse(symbol, document(zone), received=later)
                before = copy.deepcopy(original)
                self.assertNotEqual(original['receivedAt'], newly_observed['receivedAt'])
                for record in (original, newly_observed):
                    self.assertEqual(completed_bars(record)[-1][0], OLDER)
                    self.assertEqual(select(symbol, record, later)[0], {})
                self.assertEqual(original, before)

    def test_calendar_never_replaces_provider_proof_or_receipt_freshness(self):
        for symbol, zone in MARKETS:
            record = parse(symbol, document(zone, previous_close=115.))
            for changes in ({'finality': {}}, {'phase': 'unknown'},
                            {'receivedAt': (CLOCK - dt.timedelta(hours=37)).isoformat()},
                            {'receivedAt': (CLOCK + dt.timedelta(seconds=1)).isoformat()}):
                with self.subTest(symbol=symbol, changes=changes):
                    invalid = {**record, **changes}
                    before = copy.deepcopy(invalid)
                    self.assertEqual(select(symbol, invalid)[0], {})
                    self.assertEqual(invalid, before)
            self.assertFalse(fresh_record({**record, 'receivedAt': (CLOCK-dt.timedelta(hours=37)).isoformat()},
                                          CLOCK, PREVIOUS, '欧股', symbol=symbol))


if __name__ == '__main__':
    unittest.main()
