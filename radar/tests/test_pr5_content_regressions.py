"""Report evidence, source presentation, and actual HTML injection regressions."""
import copy
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import daily_changes
import notion_normalize
import render_v3
import research_view
from test_daily_changes_v3 import sample


class ParsedHTML(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.elements, self.text = [], []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, text):
        self.text.append(text)


class ReportEvidenceTests(unittest.TestCase):
    def transition(self, period, financial):
        old = daily_changes.project(sample(), {})
        current = sample('2026-10-21T12:15:00+08:00')
        current['companies'][0]['period'] = period
        current['companies'][0]['provenance']['financial'] = financial
        return daily_changes.summarize(current, [old])

    def test_period_loss_never_counts_as_a_new_report(self):
        for period in ('', None):
            for financial in ({}, {'evidence': 'missing'}, {'evidence': 'source'}):
                with self.subTest(period=period, financial=financial):
                    self.assertEqual(self.transition(period, financial)['today']['reports'], [])

    def test_period_change_without_evidence_is_not_counted(self):
        for financial in ({}, {'evidence': 'missing'}, {'status': 'unverified'},
                          {'source_urls': ['https://issuer.test/report']}):
            with self.subTest(financial=financial):
                result = self.transition('2026Q3', financial)
                self.assertEqual(result['today']['reports'], [])
                self.assertEqual(result['reports'], [])

    def test_period_change_uses_the_same_evidence_filter_as_summary(self):
        for financial in ({'evidence': 'source'}, {'evidence': 'partial'},
                          {'status': 'verified'}, {'status': 'verified_partial'}):
            with self.subTest(financial=financial):
                result = self.transition('2026Q3', financial)
                self.assertEqual(result['today']['reports'], ['A'])
                self.assertEqual([row['id'] for row in result['reports']], ['A'])

    def test_evidence_loss_does_not_erase_an_earlier_observed_report(self):
        old = daily_changes.project(sample(), {}, {'date': '2026-10-21', 'reports': ['A'],
                                                   'confirmed': [], 'scores': []})
        current = sample('2026-10-21T12:15:00+08:00')
        current['companies'][0]['period'] = ''
        current['companies'][0]['provenance']['financial'] = {'evidence': 'missing'}
        self.assertEqual(daily_changes.summarize(current, [old])['today']['reports'], ['A'])


class ResearchSourceTests(unittest.TestCase):
    internal = 'https://app.notion.com/p/knowledge'
    public = 'https://issuer.test/2026-q3'

    def test_public_first_is_stable_deduplicated_and_nonmutating(self):
        sources = [self.internal, self.public, 'https://workspace.notion.site/note',
                   'https://exchange.test/disclosure', self.public]
        original = sources[:]
        expected = [self.public, 'https://exchange.test/disclosure', self.internal,
                    'https://workspace.notion.site/note']
        self.assertEqual(research_view.public_first_sources(sources), expected)
        self.assertEqual(sources, original)
        for extract in (research_view.urls, notion_normalize.urls):
            self.assertEqual(extract('\n'.join(sources)), expected)

    def test_notion_host_classification_does_not_accept_lookalikes(self):
        for value in (self.internal, 'https://www.notion.so/p', 'https://team.notion.site/p'):
            self.assertTrue(research_view.is_notion_url(value), value)
        for value in ('https://notion.so.evil.test/p', 'https://evilnotion.so/p',
                      'https://notion.so@evil.test/p', 'https://user:password@notion.so/p'):
            self.assertFalse(research_view.is_notion_url(value), value)

    def test_sorting_does_not_invent_source_or_change_judgment_admission(self):
        props = {'研判理由': '既有理由', '研判日期': '2026-10-23', '有效至': '2026-11-02'}
        legacy = research_view.judgment({**props, '来源': self.internal}, dt.date(2026, 10, 23))
        self.assertEqual(legacy['label'], 'ai')
        self.assertEqual(legacy['sources'], [self.internal])
        missing = research_view.judgment(props, dt.date(2026, 10, 23))
        self.assertEqual(missing['label'], 'stale')
        self.assertIn('missing_source', missing['reasons'])

    def test_financial_sources_sort_without_rewriting_primary_evidence(self):
        contract = json.loads((ROOT / 'radar/data/notion_schema.json').read_text('utf-8'))
        row = {'props': {'来源链接': self.internal, '其他来源': self.public,
                         '口径': '单季', '报告状态': '正式报告'}, 'rowSource': 'notion'}
        before = copy.deepcopy(row)
        result = notion_normalize._financial_data(row, contract)
        self.assertEqual(result['source_urls'], [self.public, self.internal])
        self.assertEqual(result['source_url'], self.internal)
        self.assertEqual(row, before)


class FrontendSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'radar/site/app.js').read_text('utf-8')
        cls.esc = cls.line('const esc=')

    @classmethod
    def line(cls, prefix):
        return next(line for line in cls.source.splitlines() if line.startswith(prefix))

    def section(self, start, end):
        return self.source[self.source.index(start):self.source.index(end)]

    def run_js(self, code):
        result = subprocess.run(['node', '-e', self.esc + '\n' + code], capture_output=True,
                                encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def source_helpers(self):
        return '\n'.join(self.line('function ' + name + '(') for name in
                         ('safeResearchUrl', 'isNotionUrl', 'researchSources', 'researchAnchor'))

    def test_research_links_only_allow_https_and_label_real_notion_hosts(self):
        internal = 'https://app.notion.com/p/note'
        public = 'https://issuer.test/q3'
        rejected = ['http://issuer.test/q3', '//issuer.test/q3', 'javascript:alert(1)',
                    'https://u:p@issuer.test/q3', 'https://issuer.test/ white',
                    'https://issuer.test/\npath']
        result = self.run_js(self.source_helpers() + '\nconst invalid=' + json.dumps(rejected)
                             + '; const urls=' + json.dumps([internal, public, internal]) + ';'
                             + 'process.stdout.write(JSON.stringify({rejected:invalid.map(safeResearchUrl),'
                             + 'html:researchSources(urls).map(u=>researchAnchor(u)).join(""),'
                             + 'spoof:isNotionUrl("https://notion.so.evil.test/p")}));')
        self.assertEqual(result['rejected'], [''] * len(rejected))
        self.assertFalse(result['spoof'])
        parsed = ParsedHTML(result['html'])
        self.assertEqual([attrs['href'] for tag, attrs in parsed.elements if tag == 'a'], [public, internal])
        self.assertEqual(''.join(parsed.text), 'issuer.test ↗知识库 ↗')
        for url in rejected:
            self.assertEqual(render_v3.safe_url(url), '')
        self.assertEqual(render_v3.safe_url(public), public)

    def test_status_tag_round_trips_malicious_class_text_and_tooltip(self):
        payload = '\" onmouseover=\"alert(1)\"><img src=x onerror=alert(2)> & \' '
        result = self.run_js(self.line('function statusTag(') + '\nconst p=' + json.dumps(payload)
                             + ';process.stdout.write(JSON.stringify(statusTag(p,p,p,true)));')
        parsed = ParsedHTML(result)
        self.assertEqual([tag for tag, _ in parsed.elements], ['span'])
        attrs = parsed.elements[0][1]
        self.assertEqual(attrs['class'], 'st ' + payload + ' sm')
        self.assertEqual(attrs['data-tip'], payload)
        self.assertEqual(attrs['aria-label'], payload + '：' + payload)
        self.assertEqual(''.join(parsed.text), payload)
        self.assertFalse(any(key.startswith('on') for key in attrs))

    def test_financial_drawer_puts_public_evidence_before_knowledge_links(self):
        company = {'period': 'Q3', 'provenance': {'financial': {
            'source_urls': ['https://app.notion.com/p/record', 'https://issuer.test/report'],
            'source_url': 'https://app.notion.com/p/record'}}}
        code = self.source_helpers() + '\n' + self.section('function financialEvidence(', 'function marketEvidence(')
        code += '\nconst REPORT_STATUS={},FIN_BASIS={},financialTag=()=>"";const c=' + json.dumps(company) + ';'
        code += 'process.stdout.write(JSON.stringify(financialEvidence(c)));'
        parsed = ParsedHTML(self.run_js(code))
        self.assertEqual([attrs['href'] for tag, attrs in parsed.elements if tag == 'a'],
                         ['https://issuer.test/report', 'https://app.notion.com/p/record'])
        self.assertIn('知识库 ↗', ''.join(parsed.text))

    def test_holiday_label_describes_daily_metrics_without_promoting_intraday_price(self):
        source = '\n'.join(self.line(prefix) for prefix in
                           ('const phaseText=', 'const calendarLabel=', 'const calendarSuffix=', 'const quoteLabel='))
        calendar = {'status': 'holiday_carry', 'confidence': 'official', 'label': '休市·沿用 10/01 收盘'}
        company = {'priceAsOf': '2026-10-02', 'pricePhase': 'intraday', 'priceSource': 'provider'}
        code = source + '\nconst c=' + json.dumps(company) + ', m=' + json.dumps(calendar) + ';'
        code += '''process.stdout.write(JSON.stringify({plain:quoteLabel(c),
          carry:quoteLabel({...c,marketCalendar:m}),
          rules:quoteLabel({...c,marketCalendar:{...m,confidence:'rule_based'}}),
          unconfirmed:quoteLabel({...c,marketCalendar:{...m,confidence:'unconfirmed'}}),
          stale:quoteLabel({...c,marketCalendar:{...m,status:'stale'}}),original:c}));'''
        result = self.run_js(code)
        self.assertEqual(result['plain'], '2026-10-02 盘中 · provider')
        self.assertEqual(result['carry'], '2026-10-02 盘中 · provider · 日线 休市·沿用 10/01 收盘')
        self.assertEqual(result['rules'], result['carry'])
        self.assertEqual(result['unconfirmed'], result['plain'])
        self.assertEqual(result['stale'], result['plain'])
        self.assertEqual(result['original'], company)

    def test_calendar_warnings_are_visible_and_escaped_in_both_footers(self):
        warning = '日历待确认 <img src=x onerror="alert(1)"> & 到期'
        code = self.line('function statusTag(') + '\n' + self.section('function renderFoot(', '/* ---------- reveal / scrollspy ---------- */')
        code += '\nconst D={meta:{marketCalendar:{warnings:[' + json.dumps(warning) + ']}}};'
        code += '''const CO=[],PL={},ICON={},OP=null,isMac=false,boxes={},
          $=s=>boxes[s]||(boxes[s]={innerHTML:''}),fin=()=>false,metricGap=()=>'',
          dataStateLabel=()=>'',sharedSources=()=>'',researchNotes=()=>'',shortTime=()=>'';
          renderFoot();process.stdout.write(JSON.stringify(boxes['#foot'].innerHTML));'''
        ssr = render_v3.render_footer({'meta': {'marketCalendar': {'warnings': [warning]}}}, dt.date(2026, 10, 23))
        for markup in (self.run_js(code), ssr):
            parsed = ParsedHTML(markup)
            self.assertIn(warning, ''.join(parsed.text))
            self.assertNotIn('img', [tag for tag, _ in parsed.elements])
        baseline = render_v3.render_footer({'meta': {}}, dt.date(2026, 10, 23))
        self.assertEqual(baseline, render_v3.render_footer({'meta': {'marketCalendar': {'warnings': []}}}, dt.date(2026, 10, 23)))

    def test_provisional_holiday_label_must_keep_explicit_pending_confirmation(self):
        helpers = '\n'.join(self.line(prefix) for prefix in
                            ('const phaseText=', 'const calendarLabel=', 'const calendarSuffix=', 'const quoteLabel='))
        label = '休市·沿用 02/05 收盘（待官方确认）'
        company = {'priceAsOf': '2027-02-08', 'pricePhase': 'intraday', 'priceSource': 'provider',
                   'marketCalendar': {'status': 'holiday_carry', 'confidence': 'provisional', 'label': label}}
        code = helpers + '\nconst c=' + json.dumps(company) + ';'
        code += '''const changed=(patch)=>({...c,marketCalendar:{...c.marketCalendar,...patch}});
          process.stdout.write(JSON.stringify({valid:quoteLabel(c),
            missing:calendarLabel(changed({label:'休市·沿用 02/05 收盘'})),
            official:calendarLabel(changed({label:'休市·沿用 02/05 收盘（官方确认）'})),
            unknown:calendarLabel(changed({status:'unconfirmed'})),
            unavailable:calendarLabel(changed({confidence:'unavailable'})),original:c}));'''
        result = self.run_js(code)
        self.assertEqual(result['valid'], '2027-02-08 盘中 · provider · 日线 ' + label)
        for key in ('missing', 'official', 'unknown', 'unavailable'):
            self.assertEqual(result[key], '', key)
        self.assertEqual(result['original'], company)

    def test_company_identifiers_are_safe_in_all_four_actual_renderers(self):
        payload = '\" onmouseover=\"alert(1)\"><img src=x onerror=alert(2)> & \' '
        setup = 'const company={id:' + json.dumps(payload) + ',name:"Company",short:"Company",sc:[]};\n'
        setup += '''const boxes={}, $=s=>boxes[s]||(boxes[s]={innerHTML:'',textContent:'',dataset:{}});
          const CO=[company],D={indices:[],meta:{}},S={sel:'Industry',sort:{k:'name',d:1}},ASOFL='';
          const IND=[{name:'Industry',reps:'Company',s:[1,1,1,1],total:4}],byInd={};
          const DIMS=[],ICON={},cpsOf=()=>[],levelOf=()=>({l:''}),radarSVG=()=>'',
            judgmentOf=()=>({}),provenanceLine=()=>'',animateRadar=()=>{},researchAnchor=()=>'',
            findCo=()=>company,spark=()=>'',finLine=()=>'',ud=()=>'',pct=()=>'',
            timeDetail=()=>'',fmtPrice=()=>'',fmtNum=()=>'',phaseText=()=>'',
            calendarLabel=()=>'',calendarSuffix=()=>'',indexAvailability=()=>({missing:[],label:''});
          const COLS=[{k:'name',f:()=>''}],filtered=()=>[company],compareRows=()=>0;
        '''
        code = setup + self.line('const leadRow=') + '\n'
        code += self.section('function renderTicker(', '/* ---------- hero ---------- */')
        code += self.section('function renderIndDetail(', 'function selectInd(')
        code += self.section('function renderTable(', 'function renderLeaders(')
        code += '''\nrenderTicker();renderIndDetail();renderTable();
          process.stdout.write(JSON.stringify([leadRow(company),boxes['#tickerTrack'].innerHTML,
            boxes['#indDetail'].innerHTML,boxes['#tbl'].innerHTML]));'''
        for markup in self.run_js(code):
            parsed = ParsedHTML(markup)
            self.assertTrue(any('data-co' in attrs for _, attrs in parsed.elements))
            self.assertNotIn('img', [tag for tag, _ in parsed.elements])
            for _, attrs in parsed.elements:
                self.assertFalse(any(key.startswith('on') for key in attrs), attrs)
                if 'data-co' in attrs:
                    self.assertEqual(attrs['data-co'], payload)


if __name__ == '__main__':
    unittest.main()
