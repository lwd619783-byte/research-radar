"""Synthetic public-parser regressions for confirmed non-session tail rows.

No existing fixtures are changed. Provider parsing, finality, exact calendar
freshness and selection run unchanged except for the new tail exclusion.
"""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'radar/scripts'))
import quotes
import snapshot
import latest
import market_calendar

NOW = dt.datetime.fromisoformat('2026-10-24T05:08:00+08:00')
TW = {'sym': '2383.TW', 'mkt': '台股', 'cur': 'TWD'}


def stamp(day, time='09:00', zone='Asia/Taipei'):
    return int(dt.datetime.fromisoformat(day+'T'+time).replace(tzinfo=ZoneInfo(zone)).timestamp())


def record(days=('2025-12-31','2026-10-21','2026-10-22','2026-10-23'), *,
           now=NOW, last_volume=0, session_day='2026-10-23', close_time='13:30',
           zone='Asia/Taipei', currency='TWD', missing=(), closes=None):
    prices = list(closes) if closes is not None else [110. for _ in days]
    payload = {'chart': {'result': [{'timestamp': [stamp(day,zone=zone) for day in days],
        'meta': {'currency': currency, 'exchangeTimezoneName': zone,
                 'regularMarketTime': stamp('2026-10-22','13:30',zone),
                 'currentTradingPeriod': {'regular': {'start': stamp(session_day,zone=zone),
                    'end': stamp(session_day,close_time,zone)}}},
        'indicators': {'quote': [{'close': [None if day in missing else price for day, price in zip(days, prices)],
                                 'high': [price + 1 for price in prices],
                                 'volume': [2000]*(len(days)-1)+[last_volume]}],
                       'adjclose': [{'adjclose': prices}]}}]}}
    class PublicPayload:
        def yahoo(self, path):
            return copy.deepcopy(payload)
    with patch.object(quotes, 'stamp', side_effect=lambda **values: {
            **values, 'schemaVersion': 2, 'receivedAt': now.isoformat()}):
        return quotes.yahoo_daily(PublicPayload(), TW['sym'])


def select(value, *, now=NOW, company=TW):
    return latest.select_daily([company], {company['sym']: value}, now, calendar_policy=True)


class NonSessionTailTests(unittest.TestCase):
    def test_confirmed_holiday_tail_selects_observed_expected_close_without_rewriting(self):
        value = record()
        before = copy.deepcopy(value)
        self.assertEqual(value['asOf'], '2026-10-23')
        self.assertEqual(value['phase'], 'closed')
        self.assertEqual(snapshot.completed_bars(value)[-1][0], '2026-10-23')
        selected, result = select(value)
        daily = selected['2383.TW']
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(daily['asOf'], '2026-10-22')
        self.assertEqual([bar[0] for bar in daily['bars']], ['2025-12-31','2026-10-21','2026-10-22'])
        self.assertEqual(daily['bars'], value['bars'][:-1])
        self.assertEqual(daily['receivedAt'], value['receivedAt'])
        self.assertEqual(daily['finality'], value['finality'])
        self.assertEqual(daily['snapshotSelection']['sourceAsOf'], '2026-10-23')
        self.assertEqual(daily['snapshotSelection']['selectedDate'], '2026-10-22')
        self.assertEqual(value, before)
        label = market_calendar.annotate('2383.TW', daily['asOf'], NOW, completed=True)
        self.assertEqual(label['status'], 'holiday_carry')
        self.assertIn('10/22', label['label'])

    def test_zero_or_nonzero_volume_never_determines_holiday_exclusion(self):
        for volume in (0, 123456):
            with self.subTest(volume=volume):
                selected, result = select(record(last_volume=volume))
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(selected['2383.TW']['asOf'], '2026-10-22')

    def test_different_tail_price_is_not_copied_into_observed_expected_close(self):
        value = record(closes=(4700., 4990., 5070., 6123.))
        before = copy.deepcopy(value)
        selected, result = select(value)
        daily = selected['2383.TW']
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(daily['bars'][-1], ['2026-10-22', 5070., 5070., 5071.])
        self.assertEqual(value['bars'][-1], ['2026-10-23', 6123., 6123., 6124.])
        self.assertEqual(daily['bars'], before['bars'][:-1])
        self.assertEqual(daily['snapshotSelection']['sourceAsOf'], '2026-10-23')
        self.assertEqual(value, before)

    def test_confirmed_holiday_and_weekend_tail_removed_but_earlier_history_retained(self):
        now = dt.datetime.fromisoformat('2026-10-26T14:00:00+08:00')
        value = record(days=('2025-12-31','2026-10-21','2026-10-22','2026-10-23',
                            '2026-10-24','2026-10-25','2026-10-26'), now=now, session_day='2026-10-26')
        selected, result = select(value,now=now)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([bar[0] for bar in selected['2383.TW']['bars']],
                         ['2025-12-31','2026-10-21','2026-10-22'])

    def test_missing_or_null_expected_close_does_not_use_an_older_day(self):
        for value in (record(days=('2026-10-21','2026-10-23')),
                      record(missing=('2026-10-22',))):
            with self.subTest(bars=value['bars']):
                selected, result = select(value)
                self.assertEqual(selected, {})
                self.assertEqual(result['status'], 'incomplete')

    def test_invalid_or_absent_provider_finality_is_not_replaced_with_calendar_proof(self):
        for mutate in (lambda r:r['finality'].update(method='untrusted'),
                       lambda r:r['barTimestamps'].pop('2026-10-22'),
                       lambda r:r.update(phase='unknown')):
            value = record(); mutate(value)
            selected, result = select(value)
            self.assertEqual(selected, {})
            self.assertEqual(result['status'], 'incomplete')

    def test_old_receipt_stays_rejected_even_when_expected_close_is_present(self):
        value = record()
        now = NOW+dt.timedelta(hours=37)
        self.assertTrue(any(bar[0]=='2026-10-22' for bar in snapshot.completed_bars(value)))
        self.assertEqual(select(value,now=now)[0], {})

    def test_legacy_closed_marker_cannot_authorize_holiday_tail_removal(self):
        for missing in (('finality',), ('barTimestamps',), ('finality','barTimestamps')):
            with self.subTest(missing=missing):
                value = record()
                for key in missing:
                    value.pop(key)
                before = copy.deepcopy(value)
                self.assertEqual(select(value)[0], {})
                self.assertEqual(value, before)

    def test_no_tail_legacy_closed_series_keeps_its_existing_compatibility(self):
        value = record(days=('2025-12-31','2026-10-21','2026-10-22'))
        value.pop('finality'); value.pop('barTimestamps')
        before = copy.deepcopy(value)
        selected, result = select(value)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(selected['2383.TW']['bars'], before['bars'])
        self.assertEqual(value, before)

    def test_wrong_provider_timezone_stays_rejected(self):
        value = record(zone='Asia/Tokyo')
        self.assertEqual(select(value)[0], {})

    def test_completed_normal_trading_day_after_expected_cannot_be_skipped(self):
        now = dt.datetime.fromisoformat('2026-10-22T12:00:00+08:00')
        # The provider claims an early completed session on an actual trading
        # day. It must not make the selector silently fall back to 10/21.
        for volume in (0, 123456):
            value = record(days=('2026-10-21','2026-10-22'), now=now,
                           session_day='2026-10-22', close_time='11:00', last_volume=volume)
            self.assertEqual(snapshot.completed_bars(value)[-1][0], '2026-10-22')
            self.assertEqual(market_calendar.context('2383.TW',now)['expectedCompletedDate'], '2026-10-21')
            self.assertEqual(select(value,now=now)[0], {})

    def test_unfinished_normal_trading_day_preserves_existing_prior_close_selection(self):
        now = dt.datetime.fromisoformat('2026-10-22T12:00:00+08:00')
        value = record(days=('2026-10-21','2026-10-22'),now=now,session_day='2026-10-22')
        self.assertEqual(value['phase'], 'intraday')
        selected, result = select(value,now=now)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(selected['2383.TW']['asOf'], '2026-10-21')

    def test_future_provider_date_blocks_even_if_provider_finality_already_dropped_it(self):
        value = record(days=('2026-10-21','2026-10-22','2026-10-23','2026-10-25'))
        self.assertEqual(select(value)[0], {})
        # A contradictory cached closed marker cannot hide the future source
        # date behind completed_bars' filtering of the invalid future row.
        value['phase'] = 'closed'
        self.assertTrue(any(bar[0]=='2026-10-22' for bar in snapshot.completed_bars(value)))
        self.assertEqual(select(value)[0], {})

    def test_provisional_weekday_holiday_cannot_discard_observed_tail(self):
        now = dt.datetime.fromisoformat('2027-02-09T14:00:00+08:00')
        company = {'sym':'600000.SS','mkt':'A股','cur':'CNY'}
        value = record(days=('2027-02-03','2027-02-04','2027-02-08'), now=now,
                       session_day='2027-02-08', zone='Asia/Shanghai', currency='CNY', close_time='15:00')
        self.assertEqual(market_calendar.context(company['sym'],now)['confidence'],'provisional')
        self.assertFalse(market_calendar.known_non_session(company['sym'],'2027-02-08'))
        self.assertEqual(select(value,now=now,company=company)[0], {})

    def test_provisional_without_conflicting_tail_keeps_pending_confirmation_label(self):
        now = dt.datetime.fromisoformat('2027-02-09T14:00:00+08:00')
        company = {'sym':'600000.SS','mkt':'A股','cur':'CNY'}
        value = record(days=('2027-02-03','2027-02-04'), now=now,
                       session_day='2027-02-08', zone='Asia/Shanghai', currency='CNY', close_time='15:00')
        selected, result = select(value,now=now,company=company)
        self.assertEqual(result['status'],'complete')
        label = market_calendar.annotate(company['sym'], selected[company['sym']]['asOf'],now,completed=True)
        self.assertEqual(label['confidence'],'provisional')
        self.assertIn('待官方确认',label['label'])

    def test_only_reviewed_calendar_coverage_can_authorize_tail_exclusion(self):
        self.assertFalse(market_calendar.known_non_session('2383.TW','2025-12-28'))
        self.assertFalse(market_calendar.known_non_session('2383.TW','2028-01-01'))
        self.assertFalse(market_calendar.known_non_session('UNKNOWN','2026-10-23'))
        self.assertTrue(market_calendar.known_non_session('2383.TW','2026-10-24'))


if __name__ == '__main__':
    unittest.main()
