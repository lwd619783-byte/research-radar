"""Offline Yahoo parser regressions for observations before the exchange close."""
import copy
import datetime as dt
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
import latest
import market_calendar
import quotes
from integrity import release_blockers
from test_integrity import dataset
from test_pr5_calendar_release import synthetic_market
from test_twse_close_integration import EXECUTION, NOW as TWSE_NOW, enriched


KOREA = {'sym': '000660.KS', 'mkt': '韩股', 'cur': 'KRW'}
DAY = '2026-11-09'
FRIDAY = '2026-11-06'
THURSDAY = '2026-11-05'
KOREA_CLOCK = dt.datetime.fromisoformat(DAY + 'T15:05:00+09:00')


def local_time(day, time, zone):
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time.fromisoformat(time), ZoneInfo(zone))


def yahoo_record(company, days, received, provider_end, *, previous_close=115., tail_time=None):
    """Use synthetic prices and receipt; leave provider parsing and proof intact."""
    spec = market_calendar.calendar_data()['exchanges'][market_calendar.exchange_for(company['sym'])]
    zone = spec['timezone']
    opening = [int(local_time(day, spec['open'], zone).timestamp()) for day in days]
    timestamps = opening.copy()
    if tail_time:
        timestamps[-1] = int(local_time(days[-1], tail_time, zone).timestamp())
    closes = [100.] * (len(days) - 2) + [previous_close, 999.]
    payload = {'chart': {'result': [{
        'meta': {'currency': company['cur'], 'exchangeTimezoneName': zone,
                 'currentTradingPeriod': {'regular': {
                     'start': opening[-1],
                     'end': int(local_time(days[-1], provider_end, zone).timestamp())}}},
        'timestamp': timestamps,
        'indicators': {'quote': [{'close': closes,
                                  'high': [close + 5 if close is not None else None for close in closes]}],
                       'adjclose': [{'adjclose': closes}]},
    }]}}

    class OfflineYahoo:
        def yahoo(self, path):
            return copy.deepcopy(payload)

    with patch.object(quotes, 'stamp', side_effect=lambda **fields: {
            **fields, 'schemaVersion': 2, 'receivedAt': received.isoformat()}):
        return quotes.yahoo_daily(OfflineYahoo(), company['sym'])


def select(company, record, now):
    return latest.select_daily([company], {company['sym']: record}, now,
                               calendar_policy=True, require_reviewed_close=True)


class PrematureCloseTests(unittest.TestCase):
    def setUp(self):
        network = patch('socket.socket', side_effect=AssertionError('Offline only'))
        network.start()
        self.addCleanup(network.stop)

    def assert_selected(self, company, record, clock, expected):
        original = copy.deepcopy(record)
        selected, meta = select(company, record, clock)
        self.assertEqual(meta['status'], 'complete')
        daily = selected[company['sym']]
        self.assertEqual(daily['phase'], 'closed')
        self.assertEqual(daily['asOf'], expected)
        self.assertEqual(daily['bars'], [bar for bar in original['bars'] if bar[0] <= expected])
        self.assertEqual(daily['finality'], original['finality'])
        self.assertEqual(daily['receivedAt'], original['receivedAt'])
        self.assertEqual(daily['snapshotSelection']['sourceAsOf'], original['asOf'])
        self.assertEqual(daily['snapshotSelection']['sourcePhase'], original['phase'])
        self.assertEqual(record, original)

    def assert_blocked(self, company, record, clock):
        selected, meta = select(company, record, clock)
        self.assertEqual(selected, {})
        self.assertEqual(meta['status'], 'incomplete')

    def test_korea_1505_uses_the_observed_previous_close(self):
        record = yahoo_record(KOREA, (THURSDAY, FRIDAY, DAY), KOREA_CLOCK, '15:00')
        self.assertEqual(record['phase'], 'closed')
        self.assertEqual(record['asOf'], DAY)
        self.assertEqual(market_calendar.context(KOREA['sym'], KOREA_CLOCK)['expectedCompletedDate'], FRIDAY)
        self.assert_selected(KOREA, record, KOREA_CLOCK, FRIDAY)

    def test_release_accepts_only_an_observed_previous_close_before_korea_close(self):
        data, _ = dataset()
        market = synthetic_market(data, KOREA_CLOCK)
        for previous in (115., None):
            with self.subTest(previous=previous):
                market['daily'][KOREA['sym']] = record = yahoo_record(
                    KOREA, (THURSDAY, FRIDAY, DAY), KOREA_CLOCK, '15:00', previous_close=previous)
                result, _, _ = build.assemble(data, market, market, KOREA_CLOCK, calendar_policy=True)
                result['meta']['fixture'] = True
                blockers = release_blockers(result)
                company = next(c for c in result['companies'] if c['sym'] == KOREA['sym'])
                if previous is None:
                    self.assertNotIn(FRIDAY, record['barTimestamps'])
                    self.assertIsNone(company['ld'])
                    self.assertIn('mixed_or_missing_market_dates_need_label_approval', blockers)
                else:
                    self.assertEqual(company['ld'], FRIDAY)
                    self.assertEqual(blockers, ['synthetic_fixture_not_publishable'])

    def test_korea_close_boundary_needs_a_new_post_close_receipt(self):
        early = yahoo_record(KOREA, (FRIDAY, DAY), KOREA_CLOCK, '15:00')
        for clock in (KOREA_CLOCK.replace(minute=30), KOREA_CLOCK.replace(hour=16)):
            with self.subTest(clock=clock):
                self.assertEqual(market_calendar.context(KOREA['sym'], clock)['expectedCompletedDate'], DAY)
                self.assert_blocked(KOREA, early, clock)
                after_close = yahoo_record(KOREA, (FRIDAY, DAY), clock, '15:30')
                self.assertEqual(after_close['phase'], 'closed')
                self.assert_selected(KOREA, after_close, clock, DAY)

    def test_korea_premature_receipt_cannot_be_promoted_next_morning(self):
        record = yahoo_record(KOREA, (FRIDAY, DAY), KOREA_CLOCK, '15:00')
        next_morning = local_time('2026-11-10', '08:45', 'Asia/Seoul')
        self.assertEqual(market_calendar.context(KOREA['sym'], next_morning)['expectedCompletedDate'], DAY)
        self.assert_blocked(KOREA, record, next_morning)

    def test_calendar_does_not_promote_non_closed_provider_records(self):
        after_close = KOREA_CLOCK.replace(hour=16)
        for phase, hour, minute, tail_time in (
                ('preopen', 8, 55, '08:55'), ('intraday', 15, 29, None)):
            with self.subTest(phase=phase):
                receipt = KOREA_CLOCK.replace(hour=hour, minute=minute)
                record = yahoo_record(KOREA, (FRIDAY, DAY), receipt, '15:30', tail_time=tail_time)
                self.assertEqual(record['phase'], phase)
                self.assert_selected(KOREA, record, receipt, FRIDAY)
                self.assert_blocked(KOREA, record, after_close)
        unknown = yahoo_record(KOREA, (FRIDAY, DAY), after_close, '15:30', tail_time='15:31')
        self.assertEqual(unknown['phase'], 'unknown')
        self.assert_blocked(KOREA, unknown, after_close)

    def test_other_markets_respect_the_exchange_close(self):
        for symbol, market, currency, zone, close in (
                ('ENR.DE', '欧股', 'EUR', 'Europe/Berlin', '17:30'),
                ('SU.PA', '欧股', 'EUR', 'Europe/Paris', '17:30'),
                ('NVDA', '美股', 'USD', 'America/New_York', '16:00'),
                ('3110.T', '日股', 'JPY', 'Asia/Tokyo', '15:30'),
                ('2383.TW', '台股', 'TWD', 'Asia/Taipei', '13:30')):
            with self.subTest(symbol=symbol):
                company = {'sym': symbol, 'mkt': market, 'cur': currency}
                clock = local_time(DAY, close, zone)
                before = clock - dt.timedelta(seconds=1)
                early_end = (clock - dt.timedelta(minutes=2)).strftime('%H:%M')
                premature = yahoo_record(company, (FRIDAY, DAY), before, early_end)
                intraday = yahoo_record(company, (FRIDAY, DAY), before, close)
                closed = yahoo_record(company, (FRIDAY, DAY), clock, close)
                self.assertEqual(premature['phase'], 'closed')
                self.assert_selected(company, premature, before, FRIDAY)
                self.assertEqual(intraday['phase'], 'intraday')
                self.assert_selected(company, intraday, before, FRIDAY)
                self.assertEqual(closed['phase'], 'closed')
                self.assert_selected(company, closed, clock, DAY)

    def test_reviewed_early_close_uses_the_shortened_session(self):
        company = {'sym': 'NVDA', 'mkt': '美股', 'cur': 'USD'}
        day, previous = '2026-11-27', '2026-11-25'  # Thanksgiving Thursday is closed.
        close = local_time(day, '13:00', 'America/New_York')
        before = close - dt.timedelta(seconds=1)
        premature = yahoo_record(company, (previous, day), before, '12:58')
        intraday = yahoo_record(company, (previous, day), before, '13:00')
        closed = yahoo_record(company, (previous, day), close, '13:00')
        self.assertEqual(market_calendar.context(company['sym'], before)['expectedCompletedDate'], previous)
        self.assertEqual(market_calendar.context(company['sym'], close)['expectedCompletedDate'], day)
        self.assertEqual(premature['phase'], 'closed')
        self.assert_selected(company, premature, before, previous)
        self.assert_blocked(company, premature, close)
        self.assert_selected(company, intraday, before, previous)
        self.assert_selected(company, closed, close, day)

    def test_rule_based_calendar_excludes_the_unfinished_session(self):
        company = {'sym': 'SU.PA', 'mkt': '欧股', 'cur': 'EUR'}
        day, previous = '2027-03-30', '2027-03-25'
        receipt = local_time(day, '17:29:59', 'Europe/Paris')
        premature = yahoo_record(company, (previous, day), receipt, '17:28')
        self.assertEqual(market_calendar.context(company['sym'], receipt)['confidence'], 'rule_based')
        self.assertEqual(premature['phase'], 'closed')
        self.assert_selected(company, premature, receipt, previous)

    def test_provisional_calendar_does_not_discard_a_premature_closed_tail(self):
        company = {'sym': '600000.SS', 'mkt': 'A股', 'cur': 'CNY'}
        day, previous = '2027-01-05', '2027-01-04'
        receipt = local_time(day, '14:05', 'Asia/Shanghai')
        closed = yahoo_record(company, (previous, day), receipt, '14:00')
        intraday = yahoo_record(company, (previous, day), receipt, '15:00')
        self.assertEqual(market_calendar.context(company['sym'], receipt)['confidence'], 'provisional')
        self.assertEqual(closed['phase'], 'closed')
        self.assert_blocked(company, closed, receipt)
        self.assert_selected(company, intraday, receipt, previous)

    def test_independent_twse_close_proof_remains_required(self):
        company = {'sym': '2383.TW', 'mkt': '台股', 'cur': 'TWD'}
        with patch.dict(os.environ, EXECUTION):
            raw, proven = enriched(false_holidays=True)
            self.assertEqual(raw['phase'], 'unknown')
            self.assert_blocked(company, raw, TWSE_NOW)
            self.assert_blocked(company, {**raw, 'independentCloseProof': {'verified': True}}, TWSE_NOW)
            selected, meta = select(company, proven, TWSE_NOW)
        self.assertEqual(meta['status'], 'complete')
        daily = selected[company['sym']]
        self.assertEqual(daily['asOf'], '2026-10-27')
        self.assertEqual(daily['snapshotSelection']['sourcePhase'], 'unknown')
        self.assertEqual(daily['independentCloseProof'], proven['independentCloseProof'])
        self.assertNotIn('2026-10-23', [bar[0] for bar in daily['bars']])
        self.assertNotIn('2026-10-26', [bar[0] for bar in daily['bars']])


if __name__ == '__main__':
    unittest.main()
