"""TWSE's dated emergency closure; synthetic market packets remain non-live."""
import datetime as dt
from pathlib import Path
import tempfile
import unittest

import test_pr5_calendar_release as holiday
from integrity import release_blockers
from notion_fixtures import FakeTransport, FixtureSet


ANNOUNCEMENT = ('https://www.twse.com.tw/zh/about/news/news/content.html?'
                '8a8216d6a0fa351b01a1638507a10203')


class TaiwanEmergencyClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            fixtures = FixtureSet(Path(folder) / 'fixtures')
            transport = FakeTransport(fixtures)
            cls.research, _ = holiday.build.load_research(transport=transport,
                token=fixtures.env.get('NOTION_TOKEN'), fixed_clock=fixtures.clock,
                sleep=transport.sleep, pace=transport.pace)
        cls.data, _ = holiday.dataset()
        cls.data['companies'] = cls.research['companies']
        cls.company = next(c for c in cls.data['companies'] if c['sym'] == '2383.TW')

    def assemble(self, market, now):
        result, stale, missing = holiday.build.assemble_notion(
            self.research, self.data, market, market, now)
        result['meta']['fixture'] = True
        return result, stale, missing

    def assert_accepted(self, now, day, status):
        market = holiday.synthetic_market(self.data, now)
        result, stale, missing = self.assemble(market, now)
        self.assertEqual(len(result['companies']), 42)
        self.assertEqual(len(result['indices']), 8)
        self.assertFalse(stale)
        self.assertFalse(missing)
        self.assertEqual(release_blockers(result), ['synthetic_fixture_not_publishable'])
        row = next(c for c in result['companies'] if c['sym'] == '2383.TW')
        self.assertEqual(row['ld'], day)
        self.assertEqual(row['metricAsOf'], day)
        self.assertEqual(row['priceAsOf'], day)
        self.assertEqual(row['pricePhase'], 'closed')
        self.assertEqual(row['provenance']['daily']['receivedAt'], now.isoformat())
        self.assertEqual(row['provenance']['daily']['phase'], 'closed')
        self.assertLessEqual(market['daily']['2383.TW']['finality']['end'], now.timestamp())
        note = row['marketCalendar']
        self.assertEqual(note['confidence'], 'official')
        self.assertEqual(note['expectedCompletedDate'], day)
        self.assertEqual(note['quoteDate'], day)
        self.assertEqual(note['status'], status)
        self.assertEqual(note['label'], '休市·沿用 10/22 收盘' if status == 'holiday_carry' else None)
        self.assertIn(ANNOUNCEMENT, note['sources'])
        return market

    def test_emergency_and_existing_monday_holiday_all_slots(self):
        spec = holiday.exchange('2383.TW')
        self.assertIn('2026-10-23', spec['holidays'])
        self.assertIn('2026-10-26', spec['holidays'])
        self.assertNotIn('2026-10-27', spec['holidays'])
        for day in ('2026-10-23', '2026-10-26'):
            for slot in holiday.FOUR_SLOTS:
                with self.subTest(day=day, slot=slot):
                    self.assert_accepted(holiday.clock(day, slot), '2026-10-22', 'holiday_carry')

    def test_reopening_requires_oct27_after_actual_close(self):
        for slot in ('08:45', '12:15', '13:29'):
            with self.subTest(slot=slot):
                self.assert_accepted(holiday.clock('2026-10-27', slot), '2026-10-22', 'holiday_carry')
        for slot in ('13:30', '18:15'):
            with self.subTest(slot=slot):
                now = holiday.clock('2026-10-27', slot)
                market = self.assert_accepted(now, '2026-10-27', 'current')
                market['daily']['2383.TW'] = holiday.synthetic_daily(self.company, now, '2026-10-22')
                result, stale, missing = self.assemble(market, now)
                self.assertIn('stale_quotes_not_safe_in_all_frozen_views', release_blockers(result))
                self.assertIn(self.company['name'], stale)
                self.assertIn(self.company['name'], missing)

    def test_one_missing_real_session_and_expired_receipt_still_reject(self):
        for day in ('2026-10-23', '2026-10-26'):
            for fault in ('missing_session', 'old_receipt'):
                with self.subTest(day=day, fault=fault):
                    now = holiday.clock(day, '18:15')
                    market = holiday.synthetic_market(self.data, now)
                    if fault == 'missing_session':
                        market['daily']['2383.TW'] = holiday.synthetic_daily(self.company, now, '2026-10-21')
                    else:
                        market['daily']['2383.TW']['receivedAt'] = (now - dt.timedelta(hours=37)).isoformat()
                    result, _, missing = self.assemble(market, now)
                    self.assertIn(self.company['name'], missing)
                    self.assertIn('stale_quotes_not_safe_in_all_frozen_views', release_blockers(result))
                    self.assertIn('synthetic_fixture_not_publishable', release_blockers(result))

    def test_unfinished_only_observation_cannot_be_promoted_or_fabricated(self):
        now = holiday.clock('2026-10-27', '12:15')
        for phase in ('closed', 'intraday', 'unknown'):
            with self.subTest(phase=phase):
                market = holiday.synthetic_market(self.data, now)
                record = holiday.synthetic_daily(self.company, now, '2026-10-27')
                record['phase'] = phase
                # If actual older completed bars exist, trimming the unfinished
                # tail is valid. Here the provider supplied only today's bar:
                # the calendar must neither promote it nor invent a prior close.
                record['bars'] = record['bars'][-1:]
                self.assertGreater(record['finality']['end'], now.timestamp())
                market['daily']['2383.TW'] = record
                result, _, missing = self.assemble(market, now)
                self.assertIn(self.company['name'], missing)
                self.assertIn('mixed_or_missing_market_dates_need_label_approval', release_blockers(result))
                row = next(c for c in result['companies'] if c['sym'] == '2383.TW')
                self.assertIsNone(row['ld'])
                self.assertNotEqual(row['marketCalendar']['status'], 'holiday_carry')


if __name__ == '__main__':
    unittest.main()
