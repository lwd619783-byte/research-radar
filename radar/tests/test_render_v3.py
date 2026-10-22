"""Server-rendered first-screen content, escaping, and v2 compatibility."""
import copy
import datetime as dt
from html.parser import HTMLParser
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build
from notion_fixtures import FIXTURES, FakeTransport, FixtureSet, read_json
from render_v3 import (DISCLAIMER, hero_provenance, kpi_values, pct,
                       render_fragments, render_into, render_today, safe_url)


class TextNodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)


class RenderV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = read_json(FIXTURES / 'cases.json')
        with tempfile.TemporaryDirectory(prefix='radar-ssr-test-') as directory:
            fixtures = FixtureSet(directory)
            transport = FakeTransport(fixtures)
            cls.data, _, _ = build.build_notion_data(
                transport=transport, token=fixtures.env['NOTION_TOKEN'], fixed_clock=fixtures.clock,
                quotes_data=read_json(FIXTURES / 'quotes/data-2026-10-21.json'),
                sleep=transport.sleep, pace=transport.pace, trading_days=cls.cases['trading_days'])

    def test_no_javascript_first_screen_has_final_numbers_and_real_daily_lines(self):
        fragments = render_fragments(self.data)
        self.assertEqual([row[0] for row in kpi_values(self.data)], [3, 7, 23, 25, 30])
        for value in (3, 7, 23, 25, 30):
            self.assertIn(f'data-count="{value}">{value}</span>', fragments['KPIS'])
        self.assertIn('2026-W43 · 10/19–10/25', fragments['HERO_DATE'])
        self.assertIn('AI网络与光互连', fragments['HERO_TITLE'])
        self.assertIn('显示上次结论', fragments['HERO_PROV'])
        self.assertIn('已过期', fragments['HERO_PROV'])
        self.assertIn('缩量回落，科创与创业分化', fragments['TODAY'])
        self.assertIn('多数行业修复，科技内部仍分化', fragments['TODAY'])
        self.assertIn('10/20 周二', fragments['TODAY'])
        self.assertIn('13 次请求', fragments['FOOT'])
        self.assertEqual(fragments['FOOT'].count(DISCLAIMER), 1)

    def test_notional_text_and_html_attribute_injection_is_escaped(self):
        data = copy.deepcopy(self.data)
        malicious = '<img src=x onerror="alert(1)"> & <script>alert(2)</script>'
        data['meta']['weekly'].update(focus=malicious, lead=malicious)
        data['meta']['daily']['A股'].update(line=malicious, reviewUrl='javascript:alert(3)')
        fragments = render_fragments(data)
        for key in ('HERO_TITLE', 'HERO_LEAD', 'TODAY'):
            self.assertNotIn('<img', fragments[key])
            self.assertNotIn('<script', fragments[key])
            self.assertIn('&lt;', fragments[key])
        self.assertNotIn('href="javascript:', fragments['TODAY'])

    def test_safe_external_links_have_target_and_rel(self):
        today = render_fragments(self.data)['TODAY']
        self.assertEqual(today.count('target="_blank" rel="noopener noreferrer"'), 2)
        for value in ('javascript:alert(1)', '//example.test', 'data:text/html,x', 'https://a:b@example.test', 'https://ex ample.test'):
            self.assertEqual(safe_url(value), '')
        self.assertEqual(safe_url('https://example.test/path'), 'https://example.test/path')

    def test_embedded_json_escapes_html_and_javascript_line_separators(self):
        import acceptance_bundle
        data = copy.deepcopy(self.data)
        data['meta']['title'] = '<script> & </script>\u2028\u2029'
        operations = {'note': data['meta']['title']}
        with tempfile.TemporaryDirectory() as directory:
            page = build.render(data, Path(directory), operations).read_bytes()
        self.assertEqual(acceptance_bundle.embedded_data(page), data)
        encoded = page.decode('utf-8').split('<script>const DATA=', 1)[1].split(';</script>', 1)[0]
        for raw in ('<', '>', '&', '\u2028', '\u2029'):
            self.assertNotIn(raw, encoded)
        for escaped in ('\\u003c', '\\u003e', '\\u0026', '\\u2028', '\\u2029'):
            self.assertIn(escaped, encoded)

    def test_old_data_missing_optional_v3_fields_remains_readable(self):
        data = read_json(FIXTURES / 'quotes/data-2026-10-21.json')
        fragments = render_fragments(data)
        self.assertIn('旧版数据，无研判信息', fragments['HERO_PROV'])
        self.assertEqual(fragments['TODAY'].count('今日要点待更新'), 2)
        self.assertIn('研究数据：仓库文件', fragments['FOOT'])
        self.assertEqual([row[0] for row in kpi_values(data)], [3, 7, 23, 25, 30])

    def test_auto_none_and_all_last_good_states(self):
        data = copy.deepcopy(self.data)
        data['meta']['weekly'].update(mode='none', focus='', lead='')
        fragments = render_fragments(data)
        self.assertEqual(fragments['HERO_TITLE'], '本周主线待更新')
        self.assertEqual(fragments['HERO_PROV'], '')
        self.assertEqual(fragments['HERO_LEAD'], '行业研判均待更新，下方数据照常显示。')
        data['meta']['weekly']['mode'] = 'auto'
        self.assertIn('自动生成', render_fragments(data)['HERO_PROV'])
        data['meta']['notion']['fallbackTables'] = [{'table': str(index), 'lastGoodFetchedAt': '2026-10-20T18:15:00+08:00'} for index in range(6)]
        pulse = render_fragments(data)['PULSE']
        self.assertIn('研究数据未更新', pulse)
        self.assertIn('dot warn', pulse)
        self.assertNotIn('今日变化', pulse)

    def test_kpi_boundaries_and_missing_values_are_not_zero_evidence(self):
        data = {'meta': {'today': '2026-10-21'}, 'industries': [], 'chokepoints': [], 'companies': [
            {'next': '2026-11-04', 'earnings': {'status': 'confirmed'}, 'financialSignalEligible': True, 'earng': .5, 'dd52': -.4},
            {'next': '2026-11-05', 'financialSignalEligible': True, 'earng': None, 'revg': None, 'dd52': None},
            {'next': None, 'financialSignalEligible': False, 'earng': 10, 'dd52': 0},
            {'next': '2026-10-20', 'financialPartial': True, 'financialSignalEligible': True, 'earng': 10},
        ]}
        values = kpi_values(data)
        self.assertEqual([row[0] for row in values], [0, 0, 1, 1, 1])
        self.assertEqual(values[-1][2], '官方确认 0 · 预估 1')
        data['companies'][0]['earnings']['source_url'] = 'http://issuer.example/calendar'
        self.assertEqual(kpi_values(data)[-1][2], '官方确认 0 · 预估 1')
        data['companies'][0]['earnings']['source_url'] = 'https://issuer.example/calendar'
        self.assertEqual(kpi_values(data)[-1][2], '官方确认 1 · 预估 0')

    def test_pulse_counts_cached_and_missing_company_prices_once(self):
        data = {'meta': {'today': '2026-10-21', 'generatedAt': '2026-10-21T18:15:00+08:00',
                         'stale': ['旧报价公司', '旧报价公司'],
                         'issues': [{'symbol': 'AAA', 'kind': 'daily', 'status': 'stale'}]},
                'industries': [], 'chokepoints': [], 'companies': [
                    {'id': 'A', 'name': '旧报价公司', 'sym': 'AAA', 'price': 42},
                    {'id': 'B', 'name': '无报价公司', 'sym': 'BBB', 'price': None},
                    {'id': 'C', 'name': '正常公司', 'sym': 'CCC', 'price': 50},
                ]}
        self.assertIn('2 家行情暂缺', render_fragments(data)['PULSE'])

    def test_percentage_format_uses_half_up_unicode_minus_and_missing_marker(self):
        self.assertEqual(pct(-.00025), '−0.03%')
        self.assertEqual(pct(.00025), '+0.03%')
        self.assertEqual(pct(0), '0.00%')
        self.assertEqual(pct(None), '—')

    def test_all_template_placeholders_are_replaced_deterministically(self):
        fragments = render_fragments(self.data)
        template = ''.join('<!--__SSR_' + name + '__-->' for name in fragments)
        output = render_into(template, self.data)
        self.assertNotIn('<!--__SSR_', output)
        self.assertEqual(output, render_into(template, self.data))


if __name__ == '__main__':
    unittest.main()
