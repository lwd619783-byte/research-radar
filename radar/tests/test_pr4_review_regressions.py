"""User-visible regressions from PR4's calendar, quote, HTML and release review."""
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ParsedControl(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.buttons = []
        self.text = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == 'button':
            self.buttons.append(dict(attrs))

    def handle_data(self, text):
        self.text.append(text)


class Pr4ReviewRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'radar/site/app.js').read_text('utf-8')
        cls.esc = next(line for line in cls.source.splitlines() if line.startswith('const esc='))
        cls.pulse_helpers = (
            cls.source[cls.source.index('function nextScheduledRun('):cls.source.index('function validVersion(')]
            + cls.source[cls.source.index('function shortTime('):cls.source.index('async function checkVersion(')]
        )

    def run_js(self, script):
        result = subprocess.run(['node', '-e', script], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def calendar(self, rows, today=None):
        helpers = self.source[self.source.index('function hasConfirmedEvent('):self.source.index('function eventCountdown(')]
        safe_url = self.source[self.source.index('function safeSourceUrl('):].splitlines()[0]
        script = "const TODAY='2026-10-21';\n" + helpers + safe_url
        script += '\nconst rows=' + json.dumps(rows) + ', today=' + json.dumps(today) + ';'
        script += 'process.stdout.write(JSON.stringify({counts:eventCounts(rows,today||TODAY),summary:eventSummary(rows,today||TODAY),states:rows.map(c=>eventState(c,today||TODAY))}));'
        return self.run_js(script)

    def operations(self, state='current'):
        return {'state': state, 'dataSHA256': 'a' * 64, 'sourceSHA': 'a' * 40,
                'generatedAt': '2026-10-21T08:45:00+08:00',
                'changes': {'mode': 'previous_update', 'today': {'reports': [], 'confirmed': [], 'scores': []}}}

    def render(self, *, companies=(), stale=(), missing=(), issues=(), operations=None, remote=None,
               fallback=(), now='2026-10-21T10:00:00+08:00'):
        data = {'meta': {'generatedAt': '2026-10-21T08:45:00+08:00',
                         'schedule': {'nextRunAt': '2026-10-21T08:45:00+08:00',
                                      'lateAfterMinutes': 90,
                                      'cronUtc': ['45 0 * * 1-5', '15 4 * * 1-5', '15 10 * * 1-5']},
                         'notion': {'fallbackTables': fallback}, 'stale': stale, 'missing': missing, 'issues': issues}}
        setup = 'const D=' + json.dumps(data) + '; const OP=' + json.dumps(operations or self.operations()) + ';\n'
        setup += 'const CO=' + json.dumps(companies) + '; const remoteVersion=' + json.dumps(remote) + ';\n'
        setup += 'Date.now=()=>Date.parse(' + json.dumps(now) + ');\n'
        setup += "const TODAY='2026-10-21',fin=x=>typeof x==='number'&&Number.isFinite(x);\n" + self.esc + '\n'
        setup += "const box={className:'',innerHTML:''}, $=selector=>selector==='#pulse'?box:null;\n"
        return self.run_js(setup + self.pulse_helpers + '\nrenderReleaseStatus(); process.stdout.write(JSON.stringify(box));')

    def test_calendar_counts_partition_past_today_future_and_undated(self):
        confirmed = {'status': 'confirmed', 'source_url': 'https://issuer.test/report'}
        rows = [{'next': '2026-10-22', 'earnings': confirmed},
                {'next': '2026-10-21', 'earnings': confirmed},
                {'next': '2026-10-22', 'earnings': {'status': 'estimated'}},
                {'next': '2026-10-21', 'earnings': {'status': 'confirmed'}},
                {'next': '2026-10-20', 'earnings': confirmed},
                {'next': '2026-10-20', 'earnings': {'status': 'estimated'}},
                {'next': None, 'earnings': confirmed}]
        result = self.calendar(rows)
        self.assertEqual(result['states'], ['confirmed', 'confirmed', 'unverified', 'unverified', 'overdue', 'overdue', 'undated'])
        self.assertEqual(result['counts'], {'confirmed': 2, 'estimated': 0, 'unverified': 2, 'overdue': 2, 'undated': 1})
        self.assertEqual(sum(result['counts'].values()), len(rows))
        for label in ('官方确认 2', '预估 2', '待更新 2', '待定 1'):
            self.assertIn(label, result['summary'])

    def test_past_confirmed_date_is_not_still_advertised_as_confirmed(self):
        result = self.calendar([{'next': '2026-10-20', 'earnings': {'status': 'confirmed', 'source_url': 'https://issuer.test/report'}}])
        self.assertEqual(result['counts']['confirmed'], 0)
        self.assertEqual(result['counts']['overdue'], 1)
        self.assertIn('待更新 1', result['summary'])

    def test_calendar_summary_moves_to_overdue_at_the_next_day(self):
        rows = [{'next': '2026-10-21', 'earnings': {'status': 'confirmed', 'source_url': 'https://issuer.test/report'}}]
        before = self.calendar(rows, '2026-10-21')
        after = self.calendar(rows, '2026-10-22')
        self.assertEqual(before['counts']['confirmed'], 1)
        self.assertEqual(before['counts']['overdue'], 0)
        self.assertNotIn('待更新', before['summary'])
        self.assertEqual(after['counts']['confirmed'], 0)
        self.assertEqual(after['counts']['overdue'], 1)
        self.assertIn('待更新 1', after['summary'])

    def test_segment_labels_are_literal_text_and_values_round_trip(self):
        payloads = ['<svg/onload=alert(1)>', 'AI & "光互连" <研究>']
        helpers = self.source[self.source.index('function seg('):self.source.index('function setSeg(')]
        for payload in payloads:
            with self.subTest(label=payload):
                script = self.esc + '\n' + helpers
                script += "\nconst el={dataset:{},innerHTML:''}, requestAnimationFrame=()=>{}, setSeg=(e,v)=>e.dataset.cur=v;let clicked=null;"
                script += 'const label=' + json.dumps(payload) + ';'
                script += "seg(el,[{v:label,l:label}],'all',v=>clicked=v);el.onclick({target:{closest:()=>({dataset:{v:label}})}});"
                script += 'process.stdout.write(JSON.stringify({markup:el.innerHTML,clicked,selected:el.dataset.cur}));'
                output = self.run_js(script)
                parsed = ParsedControl(output['markup'])
                self.assertEqual(parsed.tags, ['span', 'button'])
                self.assertEqual(parsed.buttons[0]['data-v'], payload)
                self.assertEqual(''.join(parsed.text), payload)
                self.assertEqual(output['clicked'], payload)
                self.assertEqual(output['selected'], payload)

    def test_no_price_does_not_claim_a_cached_value(self):
        for marker in ({}, {'stale': ['NEW']}, {'missing': ['NEW']}):
            with self.subTest(marker=marker):
                result = self.render(companies=[{'id': 'NEW', 'price': None}], **marker)
                self.assertEqual(result['className'], 'pulse warn')
                self.assertIn('1 家行情暂缺', result['innerHTML'])
                self.assertNotIn('显示上次值', result['innerHTML'])

    def test_real_cached_price_is_counted_once_by_id_symbol_or_name(self):
        company = {'id': 'CACHE', 'sym': 'C.US', 'name': '缓存公司', 'price': 123.4}
        for marker in ('CACHE', 'C.US', '缓存公司'):
            with self.subTest(marker=marker):
                result = self.render(companies=[company], stale=[marker], missing=[marker])
                self.assertEqual(result['className'], 'pulse warn')
                self.assertIn('1 家行情暂缺，显示上次值', result['innerHTML'])
                self.assertNotIn('2 家', result['innerHTML'])

    def test_invalid_prices_are_missing_even_when_marked_cached(self):
        for value in ('123.4', True, float('nan'), float('inf')):
            with self.subTest(price=value):
                result = self.render(companies=[{'id': 'INVALID', 'price': value}], stale=['INVALID'])
                self.assertEqual(result['className'], 'pulse warn')
                self.assertIn('1 家行情暂缺', result['innerHTML'])
                self.assertNotIn('显示上次值', result['innerHTML'])

    def test_daily_issue_and_company_stale_markers_preserve_cached_quote_warning(self):
        company = {'id': 'CACHE', 'sym': 'AAA', 'price': 123.4}
        for status in ('stale', 'no_common_completed_observation'):
            with self.subTest(status=status):
                issue = {'symbol': 'AAA', 'kind': 'daily', 'status': status}
                result = self.render(companies=[company], issues=[issue])
                self.assertIn('1 家行情暂缺，显示上次值', result['innerHTML'])
                missing = self.render(companies=[{**company, 'price': None}], issues=[issue])
                self.assertIn('1 家行情暂缺', missing['innerHTML'])
                self.assertNotIn('显示上次值', missing['innerHTML'])
        result = self.render(companies=[{**company, 'stale': True}])
        self.assertIn('1 家行情暂缺，显示上次值', result['innerHTML'])

    def test_non_daily_or_other_company_issue_does_not_mark_current_quote_missing(self):
        result = self.render(companies=[{'id': 'CURRENT', 'sym': 'AAA', 'price': 123.4}],
                             issues=[{'symbol': 'AAA', 'kind': 'financial', 'status': 'stale'},
                                     {'symbol': 'OTHER', 'kind': 'daily', 'status': 'stale'}])
        self.assertEqual(result['className'], 'pulse ok')
        self.assertNotIn('行情暂缺', result['innerHTML'])

    def test_mixed_missing_and_cached_prices_preserve_both_counts_with_research_warning(self):
        result = self.render(companies=[{'id': 'NEW', 'price': None}, {'id': 'CACHE', 'price': 123.4},
                                        {'id': 'GOOD', 'price': 456.7}], stale=['NEW', 'CACHE'],
                             fallback=[{'table': 'daily'}])
        self.assertEqual(result['className'], 'pulse warn')
        self.assertIn('1 张研究表沿用上次版本', result['innerHTML'])
        self.assertIn('1 家行情暂缺', result['innerHTML'])
        self.assertIn('1 家行情暂缺，显示上次值', result['innerHTML'])
        self.assertNotIn('2 家行情暂缺，显示上次值', result['innerHTML'])

    def test_current_numeric_quote_does_not_add_missing_warning(self):
        result = self.render(companies=[{'id': 'GOOD', 'price': 0}])
        self.assertEqual(result['className'], 'pulse ok')
        self.assertNotIn('行情暂缺', result['innerHTML'])

    def test_new_success_after_old_deadline_prompts_refresh_without_false_failure(self):
        for field, value in (('dataSHA256', 'b' * 64), ('sourceSHA', 'b' * 40)):
            for local_state in ('current', 'failed'):
                with self.subTest(changed=field, local_state=local_state):
                    result = self.render(operations=self.operations(local_state),
                                         remote={**self.operations(), field: value}, now='2026-10-21T10:15:01+08:00')
                    self.assertEqual(result['className'], 'pulse ok')
                    self.assertIn('有新数据', result['innerHTML'])
                    self.assertIn('id="refreshSnapshot"', result['innerHTML'])
                    self.assertNotIn('本次更新未完成', result['innerHTML'])
                    self.assertNotIn('下次 10/21 08:45', result['innerHTML'])

    def test_new_success_keeps_missing_and_research_warnings_until_refresh(self):
        result = self.render(remote={**self.operations(), 'dataSHA256': 'b' * 64},
                             companies=[{'id': 'NEW', 'price': None}], fallback=[{'table': 'daily'}],
                             now='2026-10-21T10:15:01+08:00')
        self.assertEqual(result['className'], 'pulse warn')
        for text in ('有新数据', '1 家行情暂缺', '1 张研究表沿用上次版本'):
            self.assertIn(text, result['innerHTML'])
        self.assertNotIn('本次更新未完成', result['innerHTML'])
        self.assertNotIn('显示上次值', result['innerHTML'])

    def test_unchanged_success_does_not_hide_a_missed_new_deadline(self):
        result = self.render(remote=self.operations(), now='2026-10-21T10:15:01+08:00')
        self.assertEqual(result['className'], 'pulse bad')
        self.assertIn('本次更新未完成', result['innerHTML'])
        self.assertNotIn('有新数据', result['innerHTML'])

    def test_actual_failure_stays_red_without_a_new_success(self):
        cases = [dict(operations=self.operations('failed')),
                 dict(remote=self.operations('failed')),
                 dict(remote={**self.operations('failed'), 'sourceSHA': 'b' * 40})]
        for case in cases:
            with self.subTest(case=case):
                result = self.render(**case)
                self.assertEqual(result['className'], 'pulse bad')
                self.assertIn('本次更新未完成', result['innerHTML'])


if __name__ == '__main__':
    unittest.main()
