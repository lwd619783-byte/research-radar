"""Fixed clocks and synthetic provider proofs; no network or fixture edits."""
import copy
import contextlib
import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_calendar as calendar
import latest
import build
from integrity import fresh_record, release_blockers
from test_review_regressions import complete_dataset


def clock(day, time='18:15'):
    return dt.datetime.fromisoformat(f'{day}T{time}:00+08:00')


def daily(symbol, now, day=None):
    spec = calendar.calendar_data()['exchanges'][calendar.exchange_for(symbol)]
    day = day or calendar.context(symbol, now)['expectedCompletedDate']
    zone = ZoneInfo(spec['timezone'])
    def epoch(date):
        return dt.datetime.combine(dt.date.fromisoformat(date), dt.time.fromisoformat(spec['open']), zone).timestamp()
    days = ['2024-01-02', '2025-06-02', day]
    return {'schemaVersion': 2, 'receivedAt': now.isoformat(), 'src': 'yahoo',
            'bars': [[d, 100.0 + i, 100.0 + i, 105.0 + i] for i, d in enumerate(days)],
            'asOf': day, 'phase': 'closed', 'priceBasis': 'raw', 'returnBasis': 'yahoo-adjclose',
            'timezone': spec['timezone'], 'barTimestamps': {d: epoch(d) for d in days},
            'finality': {'method': 'provider-session-boundary', 'start': epoch(day),
                         'end': calendar.session_close(spec, dt.date.fromisoformat(day)).timestamp()}}


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.data, self.market = complete_dataset()

    def accepted(self, symbol, now, expected, *, provisional=False, carry=True):
        company = next(c for c in self.data['companies'] if c['sym'] == symbol)
        record = daily(symbol, now, expected)
        record['currency'] = company['cur']
        chosen, _ = latest.select_daily([company], {symbol: record}, now, calendar_policy=True)
        self.assertIn(symbol, chosen)
        self.assertEqual(chosen[symbol]['asOf'], expected)
        self.assertTrue(fresh_record(record, now, expected, company['mkt'], symbol=symbol))
        note = calendar.annotate(symbol, expected, now, completed=True)
        self.assertEqual(note['status'], 'holiday_carry' if carry else 'current')
        if carry:
            self.assertIn('休市·沿用', note['label'])
            self.assertEqual('待官方确认' in note['label'], provisional)
        return record

    def test_xetra_christmas_three_slots_accept_real_dec23_close(self):
        for slot in ('08:45', '12:15', '18:15'):
            with self.subTest(slot=slot):
                now = clock('2026-12-28', slot)
                self.accepted('ENR.DE', now, '2026-12-23')
                self.assertFalse(fresh_record(daily('ENR.DE', now), now, '2026-12-23', '欧股'))

    def test_january_four_slots_respect_completed_session_not_requested_holiday_assumption(self):
        for slot in ('06:50', '08:45', '12:15', '18:15'):
            for symbol in ('3110.T', '000660.KS', 'ENR.DE'):
                with self.subTest(slot=slot, symbol=symbol):
                    reopened = slot == '18:15' and symbol != 'ENR.DE'
                    self.accepted(symbol, clock('2027-01-04', slot), '2027-01-04' if reopened else '2026-12-30', carry=not reopened)
                    if reopened:
                        self.assertFalse(fresh_record(daily(symbol, clock('2027-01-04', slot), '2026-12-30'),
                            clock('2027-01-04', slot), '2026-12-30', symbol=symbol))

    def test_lunar_new_year_all_22_a_shares_and_taiwan_are_explicit_estimates(self):
        a_shares = [c['sym'] for c in self.data['companies'] if c['mkt'] == 'A股']
        self.assertEqual(len(a_shares), 22)
        for slot in ('06:50', '08:45', '12:15', '18:15'):
            for symbol in a_shares + ['2383.TW', '000660.KS']:
                with self.subTest(slot=slot, symbol=symbol):
                    expected = '2027-02-03' if symbol == '2383.TW' else '2027-02-05' if symbol == '000660.KS' else '2027-02-04'
                    self.accepted(symbol, clock('2027-02-09', slot), expected, provisional=symbol != '000660.KS')

    def test_easter_equities_have_exchange_specific_confirmed_or_pinned_rules(self):
        for date in ('2027-03-26', '2027-03-29'):
            for slot in ('08:45', '12:15', '18:15'):
                for symbol in ('ENR.DE', 'SU.PA', '0522.HK', '1888.HK'):
                    with self.subTest(date=date, slot=slot, symbol=symbol):
                        self.accepted(symbol, clock(date, slot), '2027-03-25')

    def test_closed_and_intraday_data_are_not_promoted_by_calendar(self):
        now = clock('2027-01-04', '12:15')
        c = next(c for c in self.data['companies'] if c['sym'] == '3110.T')
        record = daily('3110.T', now, '2027-01-04')
        self.assertEqual(latest.select_daily([c], {c['sym']: record}, now, calendar_policy=True)[0], {})
        record['phase'] = 'unknown'
        self.assertEqual(latest.select_daily([c], {c['sym']: record}, now, calendar_policy=True)[0], {})
        quote = {'schemaVersion': 2, 'receivedAt': now.isoformat(), 'regularMarketTime': now.timestamp() - 60,
                 'regularMarketPrice': 123., 'currency': c['cur'], 'marketState': 'REGULAR'}
        self.assertTrue(latest.select_quote(quote, None, c['mkt'], c['cur'], now, symbol=c['sym'])[0])
        self.assertEqual(latest.quote_phase(quote), 'intraday')
        quote['marketState'] = 'CLOSED'
        self.assertFalse(latest.select_quote(quote, None, c['mkt'], c['cur'], now, symbol=c['sym'])[0])

    def test_missing_session_receipt_outage_and_wrong_holiday_day_fail(self):
        now = clock('2026-12-28')
        for day in ('2026-12-22', '2026-12-24', '2026-12-28'):
            self.assertFalse(fresh_record(daily('ENR.DE', now, day), now, day, '欧股', symbol='ENR.DE'))
        record = daily('ENR.DE', now)
        record['receivedAt'] = (now-dt.timedelta(hours=37)).isoformat()
        self.assertFalse(fresh_record(record, now, record['asOf'], '欧股', symbol='ENR.DE'))
        ordinary = clock('2026-10-23')
        self.assertFalse(fresh_record(daily('3110.T', ordinary, '2026-10-22'), ordinary, '2026-10-22', '日股', symbol='3110.T'))

    def test_estimates_are_bounded_and_unknown_exchange_or_expired_table_fails(self):
        now = clock('2027-02-09')
        self.assertFalse(fresh_record(daily('688498.SS', now, '2027-02-03'), now, '2027-02-03', symbol='688498.SS'))
        self.assertFalse(calendar.date_is_fresh('UNKNOWN', '2027-02-09', now))
        self.assertFalse(calendar.date_is_fresh('ENR.DE', '2027-12-30', clock('2028-01-03')))
        # An estimate ends on the actual listed boundary, never an unlimited age exemption.
        self.assertFalse(calendar.date_is_fresh('688498.SS', '2027-02-04', clock('2027-02-15')))

    def test_expiry_warning_exactly_sixty_days_and_pending_confirmation_reminder(self):
        before = calendar.context('ENR.DE', clock('2027-10-31'))
        at = calendar.context('ENR.DE', clock('2027-11-01'))
        self.assertFalse(before['warnings'])
        self.assertTrue(any('到期' in w for w in at['warnings']))
        pending = calendar.metadata(['688498.SS', '2383.TW'], clock('2026-11-02'))
        self.assertTrue(all('待官方确认' in w for w in pending['warnings']))

    def test_half_sessions_and_dst_boundaries_are_local(self):
        # HK Christmas eve ends at 12:10, US Black Friday at 13:00 New York.
        self.assertEqual(calendar.context('0522.HK', clock('2026-12-24', '12:15'))['expectedCompletedDate'], '2026-12-24')
        self.assertEqual(calendar.context('NVDA', clock('2026-11-28', '02:01'))['expectedCompletedDate'], '2026-11-27')
        self.assertEqual(calendar.context('NVDA', clock('2026-11-28', '01:59'))['expectedCompletedDate'], '2026-11-25')
        self.assertEqual(calendar.context('NVDA', clock('2027-03-16', '03:59'))['expectedCompletedDate'], '2027-03-12')
        self.assertEqual(calendar.context('NVDA', clock('2027-03-16', '04:01'))['expectedCompletedDate'], '2027-03-15')

    def test_strict_assembler_publishes_holiday_but_rejects_real_missing_session(self):
        now = clock('2026-12-28')
        c = copy.deepcopy(next(c for c in self.data['companies'] if c['sym'] == 'ENR.DE'))
        # Independent synthetic financial evidence stays current in this market-only scenario.
        c['financial'].update(period_end='2026-09-30', published_at='2026-10-15', verified_at='2026-12-27')
        data = copy.deepcopy(self.data); data['companies'] = [c]; data['config']['indices'] = []
        market = {k: {} for k in ('daily', 'quote', 'fx', 'ratio', 'index')}
        record = daily(c['sym'], now); record['currency'] = c['cur']; market['daily'][c['sym']] = record
        result, stale, missing = build.assemble(data, market, market, now, calendar_policy=True)
        self.assertEqual(release_blockers(result), [])
        self.assertFalse(stale); self.assertFalse(missing)
        self.assertEqual(result['companies'][0]['marketCalendar']['status'], 'holiday_carry')
        self.assertEqual(result['companies'][0]['pricePhase'], 'closed')
        self.assertIn('marketCalendar', result['meta'])
        market['daily'][c['sym']] = daily(c['sym'], now, '2026-12-22')
        rejected, _, _ = build.assemble(data, market, market, now, calendar_policy=True)
        self.assertIn('stale_quotes_not_safe_in_all_frozen_views', release_blockers(rejected))

    def test_index_uses_own_exchange_and_unknown_stays_partial(self):
        now = clock('2027-03-29')
        r = {'schemaVersion': 2, 'receivedAt': now.isoformat(), 'date': '2027-03-25',
             'src': 'yahoo', 'price': 100., 'chg': .01, 'phase': 'unknown'}
        self.assertIsNotNone(latest.select_index(r, None, now, symbol='^HSI'))
        self.assertIsNone(latest.select_index({**r, 'date': '2027-03-24'}, None, now, symbol='^HSI'))
        data = {'companies': [], 'indices': [{**r, 'symbol': '^HSI', 'asOf': r['date']}], 'ratio': None,
                'meta': {'configuredIndices': ['^HSI'], 'requiredFX': [], 'fxProvenance': {}}}
        self.assertEqual(latest.coverage_matrix(data)[0]['status'], 'partial')

    def test_current_ratio_remains_available_and_partial_during_session(self):
        from test_review_regressions import monthly_record
        now = clock('2026-10-23', '12:15')
        left = monthly_record('2026-10-23')
        right = monthly_record('2026-10-23', denominator=True)
        left['receivedAt'] = right['receivedAt'] = now.isoformat()
        self.assertIsNotNone(latest.comparable_ratio(left, right, now, calendar_policy=True))
        # Same-day common observations still do not prove simultaneous closes.
        result = {'companies': [], 'indices': [], 'ratio': {'asOf': '2026-10-23'},
                  'meta': {'configuredIndices': [], 'requiredFX': [], 'fxProvenance': {}}}
        self.assertEqual(latest.coverage_matrix(result)[0]['status'], 'partial')
        stale = monthly_record('2026-10-21')
        stale['receivedAt'] = now.isoformat()
        self.assertIsNone(latest.comparable_ratio(stale, stale, now, calendar_policy=True))

    def test_production_default_collector_explicitly_enables_calendar_policy(self):
        import production_collect as collector
        from notion_fixtures import FixtureSet, FakeTransport
        class StopAtMarket(Exception):
            pass
        now = clock('2026-10-21')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); fixtures = FixtureSet(root/'fixtures'); transport = FakeTransport(fixtures)
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
                   'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH,
                   'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
                   'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a' * 40}
            def market(*args, **kwargs):
                self.assertIs(kwargs.get('calendar_policy'), True)
                raise StopAtMarket()
            with patch.object(collector.probe, 'collect', side_effect=market) as called:
                with self.assertRaises(StopAtMarket):
                    collector.collect(out=root/'out/receipt.json', work=root/'work',
                        token='offline-sentinel', transport=transport, clock=lambda: now,
                        env=env, live_dry_run=True, sleep=transport.sleep, pace=transport.pace)
                called.assert_called_once()

    def test_probe_preserves_legacy_call_shape_and_strict_production_argument(self):
        import acceptance_probe as probe
        class StopAtAssembly(Exception):
            pass
        for policy in (False, True):
            with self.subTest(calendar_policy=policy), contextlib.ExitStack() as stack:
                stack.enter_context(patch('socket.socket.connect', side_effect=AssertionError('offline test')))
                for name in ('yahoo_daily', 'tencent_daily', 'yahoo_quotes', 'index_quote', 'fx', 'monthly'):
                    stack.enter_context(patch.object(probe.quotes, name, side_effect=RuntimeError('offline test')))
                def assemble(data, market, fresh, now, **kwargs):
                    self.assertEqual(kwargs, {'calendar_policy': True} if policy else {})
                    self.assertIs(market, fresh)
                    raise StopAtAssembly()
                assembled = stack.enter_context(patch.object(probe.build, 'assemble', side_effect=assemble))
                with self.assertRaises(StopAtAssembly):
                    probe.collect(self.data, probe.Budget(), snapshot_clock=clock('2026-10-23'), calendar_policy=policy)
                assembled.assert_called_once()


if __name__ == '__main__':
    unittest.main()
