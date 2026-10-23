"""Full-universe offline holiday gates; all market values are synthetic.

Provider-shaped timestamps prove completed sessions, not live transport. These
fixtures must remain unpublishable; only the real market blockers may be empty.
"""
import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
import market_calendar as calendar
from integrity import release_blockers
from notion_fixtures import FakeTransport, FixtureSet
from test_integrity import dataset


REGULAR_SLOTS = ('08:45', '12:15', '18:15')
FOUR_SLOTS = ('06:50',) + REGULAR_SLOTS


def clock(day, slot):
    return dt.datetime.fromisoformat(f'{day}T{slot}:00+08:00')


def exchange(symbol):
    return calendar.calendar_data()['exchanges'][calendar.exchange_for(symbol)]


def synthetic_daily(company, now, day=None):
    spec = exchange(company['sym'])
    day = day or calendar.context(company['sym'], now)['expectedCompletedDate']
    end = dt.date.fromisoformat(day)
    # Long, explicitly invented history exercises every market metric. The
    # reviewed calendar determines only admissible sessions, never prices.
    dates = [end - dt.timedelta(days=i) for i in reversed(range(820))]
    days = [d.isoformat() for d in dates if calendar.is_session(spec, d)]
    def opening(value):
        return dt.datetime.combine(dt.date.fromisoformat(value),
            dt.time.fromisoformat(spec['open']), ZoneInfo(spec['timezone'])).timestamp()
    return {
        'schemaVersion': 2, 'fixture': True, 'receivedAt': now.isoformat(), 'src': 'yahoo',
        'bars': [[d, 100. + i / 100, 100. + i / 100, 110. + i / 100] for i, d in enumerate(days)],
        'asOf': day, 'phase': 'closed', 'priceBasis': 'raw', 'returnBasis': 'synthetic-adjusted',
        'currency': company['cur'], 'timezone': spec['timezone'],
        'barTimestamps': {d: opening(d) for d in days},
        'finality': {'method': 'provider-session-boundary', 'start': opening(day),
                     'end': calendar.session_close(spec, end).timestamp()},
    }


def synthetic_market(data, now):
    market = {key: {} for key in ('daily', 'quote', 'index', 'ratio', 'fx')}
    for company in data['companies']:
        symbol = company['sym']
        daily = synthetic_daily(company, now)
        market['daily'][symbol] = daily
        market['quote'][symbol] = {
            'schemaVersion': 2, 'fixture': True, 'receivedAt': now.isoformat(), 'src': 'yahoo',
            'regularMarketTime': daily['finality']['end'], 'marketState': 'CLOSED',
            'marketCap': 1e10, 'trailingPE': 20., 'currency': company['cur'],
            'regularMarketPrice': daily['bars'][-1][1],
        }
    for index in data['config']['indices']:
        symbol = index['symbol']
        spec = exchange(symbol)
        day = calendar.context(symbol, now)['expectedCompletedDate']
        market['index'][symbol] = {
            'schemaVersion': 2, 'fixture': True, 'receivedAt': now.isoformat(), 'src': 'yahoo',
            'date': day, 'price': 3000., 'chg': .01, 'phase': 'closed',
            'timezone': spec['timezone'],
            'observedAt': calendar.session_close(spec, dt.date.fromisoformat(day)).isoformat(),
        }
    # Invented OTC UTC sessions: completed weekdays, excluding Christmas and
    # New Year. Do not relabel an old equity valuation with a newer FX date.
    end = now.astimezone(dt.UTC).date() - dt.timedelta(days=1)
    dates = [end - dt.timedelta(days=i) for i in reversed(range(20))]
    days = [d for d in dates if d.weekday() < 5 and d.strftime('%m-%d') not in ('12-25', '01-01')]
    def midnight(day):
        return dt.datetime.combine(day, dt.time(), dt.UTC).timestamp()
    for currency in sorted({c['cur'] for c in data['companies']} - {'USD'}):
        market['fx'][currency] = {
            'schemaVersion': 2, 'fixture': True, 'receivedAt': now.isoformat(), 'src': 'yahoo',
            'currency': currency, 'asOf': days[-1].isoformat(), 'direction': 'USD-to-local',
            'priceBasis': 'daily-close', 'timezone': 'UTC',
            'rates': [[d.isoformat(), 7., 1 / 7 if currency == 'EUR' else 7.] for d in days],
            'rateTimestamps': {d.isoformat(): midnight(d) for d in days},
            'finality': {'method': 'provider-session-boundary',
                         'start': midnight(days[-1]), 'end': midnight(days[-1]) + 86400},
        }
    day = calendar.context('399006.SZ', now)['expectedCompletedDate']
    observed = dt.date.fromisoformat(day)
    month = observed.year * 12 + observed.month - 1
    for key in ('cyb', 'hl'):
        bars = [[f'{m // 12:04}-{m % 12 + 1:02}', 100. if key == 'hl' else 90. + i % 21]
                for i, m in enumerate(range(month - 122, month + 1))]
        bars[-1][1] = 100.
        market['ratio'][key] = {
            'schemaVersion': 2, 'fixture': True, 'receivedAt': now.isoformat(), 'src': 'tencent',
            'bars': bars, 'asOf': day, 'current': {'date': day, 'close': 100., 'src': 'tencent'},
        }
    return market


class FullHolidayReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Real normalization of supplied offline Notion fixtures. Do not renew
        # their research dates to make a market-only scenario look live/current.
        with tempfile.TemporaryDirectory() as folder:
            fixtures = FixtureSet(Path(folder) / 'fixtures')
            transport = FakeTransport(fixtures)
            cls.research, _ = build.load_research(transport=transport,
                token=fixtures.env.get('NOTION_TOKEN'), fixed_clock=fixtures.clock,
                sleep=transport.sleep, pace=transport.pace)
        cls.data, _ = dataset()
        cls.data['companies'] = cls.research['companies']

    def assemble(self, market, now):
        result, stale, missing = build.assemble_notion(
            self.research, self.data, market, market, now)
        result['meta']['fixture'] = True
        return result, stale, missing

    def assert_annotation(self, note, day):
        self.assertEqual(note['quoteDate'], day)
        self.assertEqual(note['expectedCompletedDate'], day)
        self.assertIn(note['status'], ('current', 'holiday_carry'))
        if note['status'] == 'holiday_carry':
            self.assertEqual(note['label'], f'休市·沿用 {day[5:7]}/{day[8:10]} 收盘'
                + ('（待官方确认）' if note['confidence'] == 'provisional' else ''))
        else:
            self.assertIsNone(note['label'])

    def assert_packet(self, now, expected, *, provisional=(), current=()):
        market = synthetic_market(self.data, now)
        result, stale, missing = self.assemble(market, now)
        self.assertEqual(len(market['daily']), 42)
        self.assertEqual(len(market['quote']), 42)
        self.assertEqual(len(result['companies']), 42)
        self.assertEqual(len(result['indices']), 8)
        self.assertEqual(set(market['fx']), {'CNY', 'EUR', 'HKD', 'JPY', 'KRW', 'TWD'})
        self.assertEqual(set(market['ratio']), {'cyb', 'hl'})
        self.assertEqual(stale, [])
        self.assertEqual(missing, [])
        self.assertEqual(release_blockers(result), ['synthetic_fixture_not_publishable'])
        self.assertEqual(result['meta']['blockers'], [])
        rows = {c['sym']: c for c in result['companies']}
        for symbol, row in rows.items():
            source = market['daily'][symbol]
            self.assertEqual(row['ld'], source['asOf'])
            self.assertEqual(row['metricAsOf'], source['asOf'])
            self.assertEqual(row['priceAsOf'], source['asOf'])
            self.assertEqual(row['pricePhase'], 'closed')
            self.assertEqual(row['provenance']['daily']['receivedAt'], now.isoformat())
            self.assertEqual(row['provenance']['daily']['phase'], 'closed')
            self.assertEqual(row['provenance']['valuation']['asOf'], source['asOf'])
            self.assertEqual(row['provenance']['valuation']['phase'], 'closed')
            self.assertLessEqual(source['finality']['end'], now.timestamp())
            self.assertEqual(row['provenance']['valuation']['observedAt'], source['finality']['end'])
            self.assertEqual(row['provenance']['valuation']['receivedAt'], now.isoformat())
            self.assert_annotation(row['marketCalendar'], source['asOf'])
            self.assertTrue(all(row[k] is not None for k in ('price', 'r5', 'r20', 'r60', 'ytd', 'hi52')))
        for row in result['indices']:
            source = market['index'][row['symbol']]
            self.assertEqual(row['asOf'], source['date'])
            self.assertEqual(row['phase'], 'closed')
            self.assertEqual(row['receivedAt'], now.isoformat())
            self.assertEqual(row['observedAt'], source['observedAt'])
            self.assertLessEqual(dt.datetime.fromisoformat(row['observedAt']), now)
            self.assert_annotation(row['marketCalendar'], source['date'])
        for symbol, day in expected.items():
            row = rows[symbol]
            self.assertEqual(row['ld'], day)
            note = row['marketCalendar']
            if symbol in current:
                self.assertEqual(note['status'], 'current')
            else:
                self.assertEqual(note['status'], 'holiday_carry')
                self.assertEqual(note['label'], f'休市·沿用 {day[5:7]}/{day[8:10]} 收盘'
                    + ('（待官方确认）' if symbol in provisional else ''))
        for currency, source in market['fx'].items():
            self.assertEqual(result['meta']['fxProvenance'][currency]['asOf'], source['asOf'])
            self.assertEqual(result['meta']['fxProvenance'][currency]['receivedAt'], now.isoformat())
            self.assertLessEqual(source['finality']['end'], now.timestamp())
        # A previous-month ratio cannot be promoted to this month, and two
        # daily observations do not establish simultaneous intraday observation.
        if market['ratio']['cyb']['asOf'][:7] != now.strftime('%Y-%m'):
            self.assertIsNone(result['ratio'])
        else:
            self.assertEqual(result['ratio']['asOf'], market['ratio']['cyb']['asOf'])
            self.assertFalse(result['ratio']['simultaneousObservationProven'])
            ratio_coverage = next(c for c in result['meta']['coverage'] if c['kind'] == 'ratio')
            self.assertEqual(ratio_coverage['status'], 'partial')
        return result, market

    def test_christmas_full_packet_all_three_slots(self):
        for slot in REGULAR_SLOTS:
            with self.subTest(slot=slot):
                result, _ = self.assert_packet(clock('2026-12-28', slot), {'ENR.DE': '2026-12-23'})
                enr = next(c for c in result['companies'] if c['sym'] == 'ENR.DE')
                self.assertIsNone(enr['mcapUSD'])  # The 4-day FX guard is not relaxed.

    def test_new_year_full_packet_all_four_slots(self):
        for slot in FOUR_SLOTS:
            with self.subTest(slot=slot):
                reopened = ('3110.T', '000660.KS') if slot == '18:15' else ()
                expected = {s: '2027-01-04' if s in reopened else '2026-12-30'
                            for s in ('3110.T', '000660.KS', 'ENR.DE')}
                result, _ = self.assert_packet(clock('2027-01-04', slot), expected, current=reopened)
                for row in result['companies']:
                    if row['sym'] in expected:
                        self.assertEqual(row['mcapUSD'] is None, row['sym'] not in reopened)

    def test_lunar_new_year_full_packet_all_four_slots(self):
        a_shares = [c['sym'] for c in self.data['companies'] if c['mkt'] == 'A股']
        self.assertEqual(len(a_shares), 22)
        expected = {s: '2027-02-04' for s in a_shares}
        expected.update({'2383.TW': '2027-02-03', '000660.KS': '2027-02-05'})
        provisional = a_shares + ['2383.TW']
        for slot in FOUR_SLOTS:
            with self.subTest(slot=slot):
                result, _ = self.assert_packet(clock('2027-02-09', slot), expected, provisional=provisional)
                for row in result['companies']:
                    if row['sym'] in provisional:
                        self.assertIsNone(row['mcapUSD'])

    def test_easter_full_packet_both_dates_all_three_slots(self):
        expected = {s: '2027-03-25' for s in ('ENR.DE', 'SU.PA', '0522.HK', '1888.HK')}
        for day in ('2027-03-26', '2027-03-29'):
            for slot in REGULAR_SLOTS:
                with self.subTest(day=day, slot=slot):
                    self.assert_packet(clock(day, slot), expected)

    def test_one_missing_completed_session_still_blocks_each_holiday_group(self):
        for day, symbol in (('2026-12-28', 'ENR.DE'), ('2027-01-04', '3110.T'),
                            ('2027-02-09', '300394.SZ'), ('2027-03-26', '0522.HK'),
                            ('2027-03-29', 'ENR.DE')):
            with self.subTest(day=day, symbol=symbol):
                now = clock(day, '18:15')
                market = synthetic_market(self.data, now)
                company = next(c for c in self.data['companies'] if c['sym'] == symbol)
                prior_session = market['daily'][symbol]['bars'][-2][0]
                market['daily'][symbol] = synthetic_daily(company, now, prior_session)
                result, stale, missing = self.assemble(market, now)
                self.assertIn('stale_quotes_not_safe_in_all_frozen_views', release_blockers(result))
                self.assertIn(company['name'], stale)
                self.assertIn(company['name'], missing)
                self.assertEqual(len(result['indices']), 8)
                self.assertIn('synthetic_fixture_not_publishable', release_blockers(result))

    def test_expired_receipt_cannot_be_refreshed_by_holiday_calendar(self):
        now = clock('2026-12-28', '18:15')
        market = synthetic_market(self.data, now)
        market['daily']['ENR.DE']['receivedAt'] = (now - dt.timedelta(hours=37)).isoformat()
        result, _, missing = self.assemble(market, now)
        self.assertTrue(missing)
        self.assertIn('stale_quotes_not_safe_in_all_frozen_views', release_blockers(result))


if __name__ == '__main__':
    unittest.main()
