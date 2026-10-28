"""Default production research dates are independent of stale quote payloads.

Only supplied offline fixtures and invented quote values are used. No Notion
content, protected expectations, or publication eligibility is changed here.
"""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build
import market_calendar
import research_view
from integrity import release_blockers
from notion_fixtures import FakeTransport, FixtureSet
import test_pr5_calendar_release as holiday


def clock(value):
    return dt.datetime.fromisoformat(value)


def daily_row(market, day, line=None):
    return {'id': f'{market}-{day}', 'last_edited_time': '2026-10-27T00:00:00Z',
            'props': {'标题': f'{day} {market}', '市场': market, '日期': day,
                      '一句话': line or f'已核实的{market}{day}要点',
                      '复盘链接': 'https://issuer.test/review', '涉及行业': []}}


class DefaultCompletedDailyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            fixtures = FixtureSet(Path(folder) / 'fixtures')
            transport = FakeTransport(fixtures)
            cls.research, _ = build.load_research(
                transport=transport, token=fixtures.env.get('NOTION_TOKEN'),
                fixed_clock=fixtures.clock, sleep=transport.sleep, pace=transport.pace)
        cls.config_data, _ = holiday.dataset()
        cls.config_data['companies'] = cls.research['companies']

    def inputs(self, rows, *, market_dates=None, indices=None):
        research = copy.deepcopy(self.research)
        research['daily_rows'] = rows
        research['notion']['warnings'] = []
        market = {'meta': {'snapshot': {'sourceAsOfByMarket': market_dates or
                                      {'A股': ['2026-10-23'], '美股': ['2026-10-26']}},
                          'blockers': ['mixed_or_missing_market_dates_need_label_approval']},
                  'companies': [{'sym': '688012.SS', 'mkt': 'A股', 'cur': 'CNY',
                                 'price': 10, 'priceAsOf': '2026-10-23',
                                 'ld': '2026-10-23', 'metricAsOf': '2026-10-23',
                                 'provenance': {'daily': {'asOf': '2026-10-23',
                                                        'src': 'synthetic-test'}}}],
                  'indices': indices or [], 'ratio': None}
        return research, market

    def apply(self, when, rows, **kwargs):
        research, market = self.inputs(rows, **kwargs)
        before_research, before_market = copy.deepcopy(research), copy.deepcopy(market)
        result = build.apply_research(market, research, clock(when))
        self.assertEqual(research, before_research)
        self.assertEqual(market, before_market)
        return result

    def test_old_quotes_do_not_make_completed_notion_content_future(self):
        result = self.apply('2026-10-27T00:50:00+08:00',
                            [daily_row('A股', '2026-10-23'), daily_row('A股', '2026-10-26')])
        item = result['meta']['daily']['A股']
        self.assertEqual(item['date'], '2026-10-26')
        self.assertEqual(item['source'], 'ai')
        self.assertEqual(item['line'], '已核实的A股2026-10-26要点')
        self.assertEqual(item['reviewUrl'], 'https://issuer.test/review')
        self.assertEqual(result['meta']['notion']['warnings'], [])
        self.assertEqual(result['meta']['snapshot']['sourceAsOfByMarket']['A股'], ['2026-10-23'])
        company = next(c for c in result['companies'] if c['sym'] == '688012.SS')
        self.assertEqual(company['priceAsOf'], '2026-10-23')
        self.assertEqual(company['metricAsOf'], '2026-10-23')
        self.assertIn('mixed_or_missing_market_dates_need_label_approval',
                      result['meta']['blockers'])

    def test_real_future_day_stays_rejected(self):
        result = self.apply('2026-10-27T00:50:00+08:00',
                            [daily_row('A股', '2026-10-26'), daily_row('A股', '2026-10-27')])
        self.assertEqual(result['meta']['daily']['A股']['date'], '2026-10-26')
        self.assertEqual(result['meta']['notion']['warnings'],
                         [{'code': 'daily_future_date', 'table': 'daily',
                           'key': '2026-10-27 A股', 'field': '日期'}])

    def test_ashare_preopen_and_intraday_do_not_select_unfinished_day(self):
        for time in ('08:45:00', '12:15:00', '14:59:59'):
            with self.subTest(time=time):
                result = self.apply(f'2026-10-27T{time}+08:00',
                                    [daily_row('A股', '2026-10-26'),
                                     daily_row('A股', '2026-10-27')])
                self.assertEqual(result['meta']['daily']['A股']['date'], '2026-10-26')
                self.assertEqual(result['meta']['notion']['warnings'][0]['code'],
                                 'daily_future_date')

    def test_official_close_boundary_admits_completed_day(self):
        result = self.apply('2026-10-27T15:00:00+08:00',
                            [daily_row('A股', '2026-10-26'), daily_row('A股', '2026-10-27')])
        self.assertEqual(result['meta']['daily']['A股']['date'], '2026-10-27')
        self.assertEqual(result['meta']['notion']['warnings'], [])

    def test_beijing_midnight_keeps_each_market_completed_day(self):
        for when in ('2026-10-26T23:59:59+08:00', '2026-10-27T00:00:00+08:00'):
            with self.subTest(when=when):
                result = self.apply(when, [daily_row('A股', '2026-10-26'),
                                           daily_row('美股', '2026-10-23')])
                self.assertEqual(result['meta']['daily']['A股']['date'], '2026-10-26')
                self.assertEqual(result['meta']['daily']['美股']['date'], '2026-10-23')
                self.assertEqual(result['meta']['notion']['warnings'], [])

    def test_us_overnight_intraday_not_promoted_to_completed_review(self):
        for when, expected in (('2026-10-27T00:50:00+08:00', '2026-10-23'),
                               ('2026-10-27T03:59:59+08:00', '2026-10-23'),
                               ('2026-10-27T04:00:00+08:00', '2026-10-26')):
            with self.subTest(when=when):
                result = self.apply(when, [daily_row('美股', '2026-10-23'),
                                           daily_row('美股', '2026-10-26')])
                self.assertEqual(result['meta']['daily']['美股']['date'], expected)
                self.assertEqual(result['meta']['daily']['美股']['source'], 'ai')
                self.assertEqual(len(result['meta']['notion']['warnings']),
                                 0 if expected == '2026-10-26' else 1)

    def test_intraday_us_chips_do_not_fabricate_a_completed_summary(self):
        result = self.apply('2026-10-27T00:50:00+08:00', [], indices=[
            {'symbol': '^IXIC', 'name': '纳斯达克', 'asOf': '2026-10-26',
             'phase': 'intraday', 'chg': .03}])
        self.assertEqual(result['meta']['daily']['美股'],
                         {'date': '2026-10-23', 'source': 'auto', 'line': '',
                          'reviewUrl': '', 'industries': [], 'chips': []})

    def test_confirmed_holidays_use_last_completed_session(self):
        cases = (('2026-10-01T18:15:00+08:00', 'A股', '2026-09-30', '2026-10-01'),
                 ('2026-12-25T18:15:00+08:00', '美股', '2026-12-24', '2026-12-25'))
        for when, market, expected, holiday_day in cases:
            with self.subTest(market=market):
                result = self.apply(when, [daily_row(market, expected),
                                           daily_row(market, holiday_day)])
                self.assertEqual(result['meta']['daily'][market]['date'], expected)
                self.assertEqual(result['meta']['daily'][market]['source'], 'ai')
                self.assertEqual(result['meta']['notion']['warnings'][0]['code'],
                                 'daily_future_date')

    def test_missing_timezone_does_not_guess_completed_content_date(self):
        with self.assertRaisesRegex(ValueError, '^schedule_clock_without_timezone$'):
            self.apply('2026-10-27T00:50:00', [daily_row('A股', '2026-10-26')])
        self.assertEqual(market_calendar.completed_market_dates(
            ['A股', '美股'], clock('2026-10-27T00:50:00')), {})

    def test_provisional_or_expired_calendar_does_not_admit_research_date(self):
        for when, day in (('2027-02-08T18:15:00+08:00', '2027-02-05'),
                          ('2028-01-05T18:15:00+08:00', '2028-01-04')):
            with self.subTest(when=when):
                result = self.apply(when, [daily_row('A股', day)])
                self.assertIsNone(result['meta']['daily']['A股']['date'])
                self.assertEqual(result['meta']['daily']['A股']['line'], '')
                self.assertIn({'code': 'daily_calendar_unavailable', 'table': 'daily',
                               'key': 'A股', 'field': '日期'}, result['meta']['notion']['warnings'])

    def test_unknown_market_and_disagreeing_calendars_fail_closed(self):
        self.assertEqual(market_calendar.completed_market_dates(
            ['未配置市场'], clock('2026-10-27T00:50:00+08:00')), {})
        with patch.object(market_calendar, 'context', side_effect=[
                {'expectedCompletedDate': '2026-10-23', 'confidence': 'official'},
                {'expectedCompletedDate': '2026-10-26', 'confidence': 'official'}]):
            self.assertEqual(market_calendar.completed_market_dates(
                ['A股'], clock('2026-10-27T00:50:00+08:00')), {})
        self.assertEqual(market_calendar.completed_market_dates(['A股'], None), {})

    def test_explicit_fixture_dates_remain_authoritative(self):
        research, market = self.inputs([daily_row('A股', '2026-10-23')])
        result = build.apply_research(market, research, clock('2026-10-27T00:50:00+08:00'),
                                      trading_days={'A股': '2026-10-23', '美股': '2026-10-22'})
        self.assertEqual(result['meta']['daily']['A股']['date'], '2026-10-23')
        self.assertEqual(result['meta']['daily']['A股']['source'], 'ai')
        self.assertEqual(result['meta']['daily']['美股']['date'], '2026-10-22')
        self.assertEqual(result['meta']['notion']['warnings'], [])

    def test_no_target_cannot_select_an_undated_row(self):
        result = research_view.daily_view([daily_row('A股', None)], [], {}, [])
        self.assertIsNone(result['A股']['date'])
        self.assertEqual(result['A股']['source'], 'auto')
        self.assertEqual(result['A股']['line'], '')

    def test_full_production_path_keeps_market_quality_blockers(self):
        now = clock('2026-10-27T00:50:00+08:00')
        research = copy.deepcopy(self.research)
        research['daily_rows'] = [daily_row('A股', '2026-10-26')]
        research['notion']['warnings'] = []
        market = holiday.synthetic_market(self.config_data, now)
        for company in self.config_data['companies']:
            if company['mkt'] == 'A股':
                market['daily'][company['sym']] = holiday.synthetic_daily(
                    company, now, day='2026-10-23')
        original = copy.deepcopy(market)
        result, _, _ = build.assemble_notion(research, self.config_data, market, market, now)
        result['meta']['fixture'] = True
        self.assertEqual(result['meta']['daily']['A股']['date'], '2026-10-26')
        self.assertEqual(result['meta']['daily']['A股']['source'], 'ai')
        self.assertFalse(any(w['code'] == 'daily_future_date'
                             for w in result['meta']['notion']['warnings']))
        blockers = release_blockers(result)
        self.assertIn('mixed_or_missing_market_dates_need_label_approval', blockers)
        self.assertIn('synthetic_fixture_not_publishable', blockers)
        self.assertEqual(market, original)


if __name__ == '__main__':
    unittest.main()
