"""Earnings-date boundaries use issuer-local dates without changing evidence."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

RADAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RADAR / 'scripts'))
from earnings_dates import MARKET_TIMEZONES, days_until, issuer_today, within_earnings_window
from notion_normalize import normalize
from render_v3 import kpi_values
from historical_research import historical_data, schema
from test_notion_normalize import fixture_fetch, find_page


class IssuerDateTests(unittest.TestCase):
    def test_defaults_match_frozen_contract(self):
        contract = json.loads((RADAR / 'data/notion_schema.json').read_text(encoding='utf-8'))
        self.assertEqual(MARKET_TIMEZONES, contract['market_timezones'])

    def test_beijing_midnight_does_not_expire_us_report_day(self):
        clock = '2026-11-04T01:54:00+08:00'
        self.assertEqual(str(issuer_today(clock, '美股')), '2026-11-03')
        self.assertEqual(str(issuer_today(clock, 'A股')), '2026-11-04')
        company = {'mkt': '美股', 'next': '2026-11-03'}
        self.assertEqual(days_until(company, clock), 0)
        self.assertEqual(days_until(company, '2026-11-04T13:00:00+08:00'), -1)

    def test_explicit_issuer_zone_overrides_market(self):
        clock = '2026-11-04T05:30:00Z'
        self.assertEqual(str(issuer_today(clock, '美股')), '2026-11-04')
        self.assertEqual(str(issuer_today(clock, '美股', 'America/Los_Angeles')), '2026-11-03')

    def test_dst_and_asian_date_boundaries(self):
        cases = [
            ('2026-03-08T04:59:59Z', '美股', None, '2026-03-07'),
            ('2026-03-08T05:00:00Z', '美股', None, '2026-03-08'),
            ('2026-03-09T03:59:59Z', '美股', None, '2026-03-08'),
            ('2026-03-09T04:00:00Z', '美股', None, '2026-03-09'),
            ('2026-11-01T05:30:00Z', '美股', None, '2026-11-01'),
            ('2026-11-01T06:30:00Z', '美股', None, '2026-11-01'),
            ('2026-10-25T00:30:00Z', '欧股', None, '2026-10-25'),
            ('2026-10-25T01:30:00Z', '欧股', None, '2026-10-25'),
            ('2026-11-03T15:30:00Z', '日股', None, '2026-11-04'),
            ('2026-11-03T15:30:00Z', 'A股', None, '2026-11-03'),
        ]
        for clock, market, zone, expected in cases:
            with self.subTest(clock=clock, market=market):
                self.assertEqual(str(issuer_today(clock, market, zone)), expected)

    def test_invalid_zone_retains_contract_market_fallback(self):
        clock = '2026-11-04T01:54:00+08:00'
        self.assertEqual(str(issuer_today(clock, '美股', 'Not/AZone')), '2026-11-03')
        self.assertIsNone(issuer_today(clock, '未知', 'Not/AZone'))
        self.assertEqual(str(issuer_today(clock, '未知', 'America/Los_Angeles')), '2026-11-03')

    def test_bad_clock_never_uses_host_time_or_declared_day(self):
        company = {'next': '2026-11-03', 'mkt': '美股'}
        for clock in ('', 'not-a-clock', '2026-11-04', '2026-11-04T01:54:00'):
            with self.subTest(clock=clock):
                self.assertIsNone(days_until(company, clock, legacy_today='2026-11-04'))
        self.assertIsNone(days_until(company, None))
        self.assertEqual(days_until(company, None, legacy_today='2026-11-04'), -1)
        self.assertIsNone(days_until({'next': None, 'mkt': '美股'}, '2026-11-04T01:54:00+08:00'))

    def test_fourteen_day_window_uses_each_issuers_date(self):
        clock = '2026-11-04T01:54:00+08:00'
        for day, expected in [('2026-11-02', False), ('2026-11-03', True),
                              ('2026-11-17', True), ('2026-11-18', False)]:
            self.assertEqual(within_earnings_window({'mkt': '美股', 'next': day}, clock), expected)
        self.assertTrue(within_earnings_window({'mkt': 'A股', 'next': '2026-11-18'}, clock))


class NotionEarningsDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads((RADAR / 'data/notion_schema.json').read_text(encoding='utf-8'))
        cls.original = fixture_fetch(cls.contract)

    def edited_fetch(self, zone='America/New_York', day='2026-11-03'):
        fetch = copy.deepcopy(self.original)
        page = find_page(fetch, 'companies', 'ANET')
        page['properties']['下次财报日']['date'] = {'start': day} if day else None
        page['properties']['财报日时区']['rich_text'] = ([{'type': 'text', 'plain_text': zone,
            'text': {'content': zone, 'link': None}}] if zone else [])
        return fetch, 'ANET'

    @staticmethod
    def codes(result, company_key):
        return [w['code'] for w in result['notion']['warnings'] if w.get('table') == 'companies' and w.get('key') == company_key]

    def test_live_row_warning_tracks_local_midnight_and_preserves_row(self):
        fetch, company_key = self.edited_fetch()
        original = copy.deepcopy(fetch)
        before = normalize(fetch, self.contract, '2026-11-04T01:54:00+08:00')
        after = normalize(fetch, self.contract, '2026-11-04T13:00:00+08:00')
        self.assertNotIn('earnings_date_past', self.codes(before, company_key))
        self.assertIn('earnings_date_past', self.codes(after, company_key))
        self.assertEqual(fetch, original)
        for result in (before, after):
            row = next(c for c in result['companies'] if c['id'] == 'ANET')
            self.assertEqual(row['next'], '2026-11-03')

    def test_invalid_zone_warning_remains_with_existing_market_fallback(self):
        fetch, company_key = self.edited_fetch(zone='Not/AZone')
        result = normalize(fetch, self.contract, '2026-11-04T01:54:00+08:00')
        self.assertIn('timezone_invalid', self.codes(result, company_key))
        self.assertNotIn('earnings_date_past', self.codes(result, company_key))
        self.assertEqual(next(c for c in result['companies'] if c['id'] == 'ANET')['earnings']['timezone'],
                         'America/New_York')

    def test_empty_zone_uses_market_without_changing_missing_field(self):
        fetch, company_key = self.edited_fetch(zone='')
        result = normalize(fetch, self.contract, '2026-11-04T01:54:00+08:00')
        self.assertNotIn('earnings_date_past', self.codes(result, company_key))
        self.assertEqual(next(c for c in result['companies'] if c['id'] == 'ANET')['earnings']['timezone'], '')

    def test_last_good_revalidated_at_current_local_clock(self):
        fetch, company_key = self.edited_fetch()
        first = normalize(fetch, self.contract, '2026-11-04T01:54:00+08:00')
        fetch['tables']['companies'] = {'ok': False, 'error': {'code': 'notion_timeout'}}
        same_day = normalize(fetch, self.contract, '2026-11-04T02:00:00+08:00', last_good=first['snapshot'])
        next_day = normalize(fetch, self.contract, '2026-11-04T13:00:00+08:00', last_good=first['snapshot'])
        self.assertNotIn('earnings_date_past', self.codes(same_day, company_key))
        self.assertIn('earnings_date_past', self.codes(next_day, company_key))
        self.assertTrue(any(x['table'] == 'companies' for x in next_day['notion']['fallbackTables']))

    def test_missing_date_and_source_are_not_upgraded(self):
        fetch, company_key = self.edited_fetch(day=None)
        missing = normalize(fetch, self.contract, '2026-11-04T01:54:00+08:00')
        self.assertIsNone(next(c for c in missing['companies'] if c['id'] == 'ANET')['next'])
        self.assertNotIn('earnings_date_past', self.codes(missing, company_key))
        fetch, company_key = self.edited_fetch()
        page = find_page(fetch, 'companies', 'ANET')
        page['properties']['财报日状态']['select'] = {'name': '官方确认'}
        page['properties']['财报日来源']['url'] = None
        no_source = normalize(fetch, self.contract, '2026-11-04T01:54:00+08:00')
        self.assertIn('earnings_confirmed_without_source', self.codes(no_source, company_key))
        self.assertEqual(next(c for c in no_source['companies'] if c['id'] == 'ANET')['earnings']['status'], 'unverified')


class EarningsRenderingAndConfigTests(unittest.TestCase):
    def test_ssr_counts_match_local_window_and_keep_confirmation_requirements(self):
        companies = [
            {'mkt': '美股', 'next': '2026-11-03', 'earnings': {'status': 'confirmed', 'source_url': 'https://issuer.test/a'}},
            {'mkt': '美股', 'next': '2026-11-17'},
            {'mkt': '美股', 'next': '2026-11-18'},
            {'mkt': 'A股', 'next': '2026-11-18', 'earnings': {'status': 'confirmed'}},
            {'mkt': '未知', 'next': '2026-11-04'},
            {'mkt': '美股', 'next': None},
        ]
        data = {'meta': {'today': '2026-11-04', 'generatedAt': '2026-11-04T01:54:00+08:00'}, 'companies': companies}
        self.assertEqual(kpi_values(data)[4][:3], (3, '两周内财报', '官方确认 1 · 预估 2'))
        data['meta']['generatedAt'] = '2026-11-04T01:54:00'
        self.assertEqual(kpi_values(data)[4][0], 0)

    def test_ssr_legacy_explicit_date_remains_deterministic(self):
        data = {'meta': {'today': '2026-11-04'}, 'companies': [{'next': '2026-11-04'}, {'next': '2026-11-18'}, {'next': '2026-11-19'}]}
        self.assertEqual(kpi_values(data)[4][0], 2)

    def test_toml_warning_receives_fixed_instant_without_rewriting_evidence(self):
        original_load = schema._load
        def edited_load(path, rep):
            value = original_load(path, rep)
            if path.name == 'companies.toml':
                for row in value['company']:
                    if row['id'] == 'ANET':
                        row['next_earnings'] = '2026-11-03'
                        row.setdefault('earnings', {})['timezone'] = 'America/Los_Angeles'
            return value
        with patch.object(schema, '_load', side_effect=edited_load):
            before, early = historical_data(dt.date(2026, 11, 4), fixed_clock='2026-11-04T05:30:00Z')
            after, late = historical_data(dt.date(2026, 11, 4), fixed_clock='2026-11-04T08:00:00Z')
        self.assertFalse(early.errors)
        self.assertFalse(late.errors)
        def anet_past(report):
            return [w for w in report.warnings if 'Arista' in str(w) and 'next_earnings' in str(w)]
        self.assertEqual(anet_past(early), [])
        self.assertEqual(len(anet_past(late)), 1)
        self.assertEqual(next(c for c in before['companies'] if c['id'] == 'ANET'),
                         next(c for c in after['companies'] if c['id'] == 'ANET'))


if __name__ == '__main__':
    unittest.main()
