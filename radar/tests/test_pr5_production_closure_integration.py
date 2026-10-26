"""Production Taiwan correction survives PR5's full-calendar path.

Synthetic provider records only; no original expectations or fixtures change.
"""
import copy
import datetime as dt
import unittest

import latest
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


if __name__ == '__main__':
    unittest.main()
