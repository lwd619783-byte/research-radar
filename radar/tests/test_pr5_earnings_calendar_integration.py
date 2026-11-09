"""Issuer-local earnings and completed-session research dates coexist.

Only in-memory copies of the unchanged Notion fixtures and invented quote
metadata are used; no network requests or publishable market data are made.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import unittest

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'scripts'))

import build
from earnings_dates import days_until, issuer_today
import market_calendar
from notion_normalize import normalize
from render_v3 import kpi_values
from test_notion_normalize import fixture_fetch, find_page


def daily_row(market, day):
    return {'id': f'{market}-{day}', 'last_edited_time': '2026-10-01T00:00:00Z',
            'props': {'标题': f'{day} {market}', '市场': market, '日期': day,
                      '一句话': f'{market}{day}收盘摘要。',
                      '复盘链接': 'https://issuer.test/review', '涉及行业': []}}


class EarningsCompletedCalendarIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((RADAR / 'data/notion_schema.json').read_text(encoding='utf-8'))
        cls.original = fixture_fetch(cls.contract)

    def merged_views(self, when):
        clock = dt.datetime.fromisoformat(when)
        fetched = copy.deepcopy(self.original)
        page = find_page(fetched, 'companies', 'ANET')
        page['properties']['下次财报日']['date'] = {'start': '2026-10-01'}
        page['properties']['财报日时区']['rich_text'] = [
            {'type': 'text', 'plain_text': 'America/New_York',
             'text': {'content': 'America/New_York', 'link': None}}]
        original_fetch = copy.deepcopy(fetched)
        research = normalize(fetched, self.contract, clock)
        self.assertEqual(fetched, original_fetch)
        research['daily_rows'] = [daily_row(market, day)
                                  for market in ('A股', '美股')
                                  for day in ('2026-09-30', '2026-10-01')]
        # Deliberately older quotes must neither date the research nor expire
        # an issuer's scheduled report day. Price/provenance stay unchanged.
        market = {'meta': {'snapshot': {'sourceAsOfByMarket':
                                       {'A股': ['2026-09-29'], '美股': ['2026-09-29']}},
                           'blockers': ['mixed_or_missing_market_dates_need_label_approval']},
                  'companies': [{'sym': 'ANET', 'mkt': '美股', 'cur': 'USD',
                                 'price': 10, 'priceAsOf': '2026-09-29',
                                 'ld': '2026-09-29', 'metricAsOf': '2026-09-29',
                                 'provenance': {'daily': {'asOf': '2026-09-29',
                                                        'src': 'synthetic-test'}}}],
                  'indices': [], 'ratio': None}
        original_research, original_market = copy.deepcopy(research), copy.deepcopy(market)
        result = build.apply_research(market, research, clock)
        self.assertEqual(research, original_research)
        self.assertEqual(market, original_market)
        company = next(c for c in result['companies'] if c['id'] == 'ANET')
        self.assertEqual(company['next'], '2026-10-01')
        self.assertEqual(company['earnings']['timezone'], 'America/New_York')
        self.assertEqual(company['priceAsOf'], '2026-09-29')
        self.assertEqual(company['price'], 10)
        self.assertIn('mixed_or_missing_market_dates_need_label_approval', result['meta']['blockers'])
        self.assertEqual(result['meta']['daily']['A股']['date'], '2026-09-30')
        self.assertEqual(result['meta']['daily']['A股']['source'], 'ai')
        self.assertEqual(result['meta']['daily']['A股']['line'], 'A股2026-09-30收盘摘要。')
        self.assertFalse(market_calendar.context('000001.SS', clock)['sessionToday'])
        return result, company

    @staticmethod
    def company_codes(result):
        return [w['code'] for w in result['meta']['notion']['warnings']
                if w.get('table') == 'companies' and w.get('key') == 'ANET']

    def test_beijing_next_day_ashare_holiday_keeps_us_issuer_today(self):
        result, company = self.merged_views('2026-10-02T01:30:00+08:00')
        # Beijing is on the holiday, New York is still Oct 1, and its Oct 1
        # trading session has not closed: three intentionally distinct dates.
        self.assertEqual(result['meta']['today'], '2026-10-02')
        self.assertEqual(str(issuer_today(result['meta']['generatedAt'], '美股')), '2026-10-01')
        self.assertEqual(days_until(company, result['meta']['generatedAt']), 0)
        self.assertNotIn('earnings_date_past', self.company_codes(result))
        self.assertEqual(result['meta']['daily']['美股']['date'], '2026-09-30')
        self.assertEqual(result['meta']['daily']['美股']['source'], 'ai')
        self.assertEqual(kpi_values({'meta': result['meta'], 'companies': [company]})[4][0], 1)

    def test_us_local_midnight_expires_event_but_not_ashare_holiday_review(self):
        result, company = self.merged_views('2026-10-02T12:15:00+08:00')
        self.assertEqual(result['meta']['today'], '2026-10-02')
        self.assertEqual(str(issuer_today(result['meta']['generatedAt'], '美股')), '2026-10-02')
        self.assertEqual(days_until(company, result['meta']['generatedAt']), -1)
        self.assertIn('earnings_date_past', self.company_codes(result))
        self.assertEqual(result['meta']['daily']['美股']['date'], '2026-10-01')
        self.assertEqual(result['meta']['daily']['美股']['source'], 'ai')
        self.assertEqual(kpi_values({'meta': result['meta'], 'companies': [company]})[4][0], 0)


if __name__ == '__main__':
    unittest.main()
