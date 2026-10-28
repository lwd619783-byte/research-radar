"""Production Taiwan correction survives PR5's full-calendar path.

Synthetic provider records only; no original expectations or fixtures change.
"""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest

import latest
from integrity import release_blockers
from notion_fixtures import FakeTransport, FixtureSet
import test_pr5_calendar_release as holiday
from test_completed_snapshot import epoch
from test_reviewed_taiwan_closures import NOW, TW, record


def choose(value, now=NOW, *, calendar_policy=True):
    return latest.select_daily([TW], {TW['sym']: value}, now,
                               calendar_policy=calendar_policy)[0]


class ProductionClosureIntegrationTests(unittest.TestCase):
    def test_both_paths_keep_real_close_and_original_false_source_date(self):
        value = record()
        value['bars'][-1][1:] = [99999., 99999., 100000.]
        before = copy.deepcopy(value)
        for policy in (False, True):
            with self.subTest(calendar_policy=policy):
                chosen = choose(value, calendar_policy=policy)['2383.TW']
                self.assertEqual(chosen['asOf'], '2026-10-22')
                self.assertEqual(chosen['bars'], before['bars'][:-1])
                self.assertEqual(chosen['snapshotSelection']['sourceAsOf'], '2026-10-23')
                self.assertEqual(chosen['receivedAt'], before['receivedAt'])
        self.assertEqual(value, before)

    def test_calendar_path_removes_disproven_history_after_reopening(self):
        now = dt.datetime.fromisoformat('2026-10-28T18:15:00+08:00')
        value = record(('2026-10-21', '2026-10-22', '2026-10-23', '2026-10-27', '2026-10-28'),
                       now=now, session_day='2026-10-28')
        before = copy.deepcopy(value)
        chosen = choose(value, now)['2383.TW']
        self.assertEqual([x[0] for x in chosen['bars']],
                         ['2026-10-21', '2026-10-22', '2026-10-27', '2026-10-28'])
        self.assertEqual(chosen['asOf'], '2026-10-28')
        self.assertEqual(value, before)

    def test_calendar_path_extended_carry_without_false_tail_requires_provider_proof(self):
        now = dt.datetime.fromisoformat('2026-10-27T08:45:00+08:00')
        for missing in (('finality',), ('barTimestamps',), ('finality', 'barTimestamps')):
            with self.subTest(missing=missing):
                value = record(('2026-10-21', '2026-10-22'), now=now)
                for key in missing:
                    value.pop(key)
                self.assertEqual(choose(value, now), {})

    def test_calendar_path_reopening_needs_original_receipt_and_official_close(self):
        now = dt.datetime.fromisoformat('2026-10-27T14:00:00+08:00')
        for received, end_hour in (('12:15:00', 11), ('14:00:00', 11), ('12:15:00', 13)):
            with self.subTest(received=received, end_hour=end_hour):
                source_clock = dt.datetime.fromisoformat('2026-10-27T'+received+'+08:00')
                value = record(('2026-10-21', '2026-10-22', '2026-10-27'),
                               now=source_clock, session_day='2026-10-27')
                value['finality']['end'] = epoch('2026-10-27', 'Asia/Taipei', end_hour) + (1800 if end_hour==13 else 0)
                self.assertEqual(choose(value, now), {})

    def test_calendar_path_boundary_requires_observed_reopening_day(self):
        before = dt.datetime.fromisoformat('2026-10-27T13:29:59+08:00')
        after = dt.datetime.fromisoformat('2026-10-27T13:30:00+08:00')
        value = record(now=before)
        self.assertEqual(choose(value, before)['2383.TW']['asOf'], '2026-10-22')
        self.assertEqual(choose(value, after), {})
        current = record(('2026-10-21', '2026-10-22', '2026-10-23', '2026-10-27'),
                         now=after, session_day='2026-10-27')
        selected = choose(current, after)['2383.TW']
        self.assertEqual(selected['asOf'], '2026-10-27')
        self.assertNotIn('2026-10-23', [x[0] for x in selected['bars']])

    def test_calendar_path_does_not_rejuvenate_receipt(self):
        value = record()
        value['receivedAt'] = (NOW-dt.timedelta(hours=37)).isoformat()
        self.assertEqual(choose(value), {})

    def test_calendar_quotes_reject_closed_date_but_keep_real_intraday_phase(self):
        now = dt.datetime.fromisoformat('2026-10-27T12:15:00+08:00')
        quote = {'schemaVersion': 2, 'receivedAt': now.isoformat(),
                 'regularMarketTime': epoch('2026-10-23', 'Asia/Taipei', 13),
                 'marketState': 'CLOSED', 'regularMarketPrice': 999., 'currency': 'TWD'}
        chosen, status, day = latest.select_quote(quote, '2026-10-22', '台股', 'TWD', now, symbol='2383.TW')
        self.assertEqual((chosen, status, day), ({}, 'quote_on_confirmed_market_closure', '2026-10-23'))
        quote.update(regularMarketTime=now.timestamp()-60, marketState='REGULAR')
        chosen, status, day = latest.select_quote(quote, '2026-10-22', '台股', 'TWD', now, symbol='2383.TW')
        self.assertEqual((status, day), ('available', '2026-10-27'))
        self.assertEqual(latest.quote_phase(chosen), 'intraday')
        self.assertEqual(latest.select_quote(quote, '2026-10-22', '台股', 'TWD', now)[0], {})

    def test_calendar_path_future_source_date_stays_rejected(self):
        value = record(('2026-10-21', '2026-10-22', '2026-10-23', '2026-10-28'))
        self.assertEqual(choose(value), {})

    def test_calendar_path_short_carry_rejects_provider_close_before_official_close(self):
        cases = (
            ('2026-10-23T08:45:00+08:00', '2026-10-23T08:45:00+08:00'),
            ('2026-10-24T05:08:00+08:00', '2026-10-24T05:08:00+08:00'),
            ('2026-10-26T18:15:00+08:00', '2026-10-26T18:15:00+08:00'),
            ('2026-10-23T08:45:00+08:00', '2026-10-22T12:00:00+08:00'),
        )
        for clock, receipt in cases:
            with self.subTest(clock=clock, receipt=receipt):
                now = dt.datetime.fromisoformat(clock)
                value = record(('2026-10-21', '2026-10-22'),
                               now=dt.datetime.fromisoformat(receipt), session_day='2026-10-22')
                value['finality']['end'] = epoch('2026-10-22', 'Asia/Taipei', 11)
                before = copy.deepcopy(value)
                self.assertEqual(choose(value, now), {})
                self.assertEqual(value, before)

    def test_calendar_path_short_carry_keeps_valid_original_provider_evidence(self):
        for clock in ('2026-10-23T08:45:00+08:00', '2026-10-24T05:08:00+08:00',
                      '2026-10-26T18:15:00+08:00'):
            with self.subTest(clock=clock):
                now = dt.datetime.fromisoformat(clock)
                value = record(('2026-10-21', '2026-10-22'), now=now, session_day='2026-10-22')
                before = copy.deepcopy(value)
                chosen = choose(value, now)['2383.TW']
                self.assertEqual(chosen['asOf'], '2026-10-22')
                self.assertEqual(chosen['bars'], before['bars'])
                self.assertEqual(chosen['receivedAt'], before['receivedAt'])
                self.assertEqual(chosen['finality'], before['finality'])
                self.assertEqual(value, before)

    def test_calendar_path_cannot_skip_early_closed_real_reopening_day(self):
        now = dt.datetime.fromisoformat('2026-10-27T12:15:00+08:00')
        value = record(('2026-10-22', '2026-10-27'), now=now, session_day='2026-10-27')
        value['finality']['end'] = epoch('2026-10-27', 'Asia/Taipei', 11)
        value['phase'] = 'closed'
        self.assertEqual(choose(value, now), {})


class ProductionClosurePublicationTests(unittest.TestCase):
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

    def test_notion_production_cannot_publish_unproven_legacy_short_carry(self):
        for day in ('2026-10-23', '2026-10-24', '2026-10-26'):
            with self.subTest(day=day):
                now = holiday.clock(day, '18:15')
                market = holiday.synthetic_market(self.data, now)
                value = market['daily']['2383.TW']
                self.assertEqual(value['asOf'], '2026-10-22')
                for key in ('finality', 'barTimestamps', 'timezone'):
                    value.pop(key)
                before = copy.deepcopy(market)
                result, _, missing = holiday.build.assemble_notion(
                    self.research, self.data, market, market, now)
                result['meta']['fixture'] = True
                self.assertEqual(len(result['companies']), 42)
                company = next(c for c in result['companies'] if c['sym'] == '2383.TW')
                self.assertIsNone(company['ld'])
                self.assertIsNone(company['metricAsOf'])
                self.assertIn(company['name'], missing)
                blockers = release_blockers(result)
                self.assertIn('mixed_or_missing_market_dates_need_label_approval', blockers)
                self.assertIn('synthetic_fixture_not_publishable', blockers)
                self.assertEqual(market, before)


if __name__ == '__main__':
    unittest.main()
