"""Issuer-local earnings dates through the actual calendar and drawer renderers."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'radar/site/app.js').read_text(encoding='utf-8')
NODE = shutil.which('node')
sys.path.insert(0, str(ROOT / 'radar/scripts'))
from earnings_dates import issuer_today
HELPERS = SOURCE.split('/* ---------- research and calendar validity ---------- */')[1].split('/* ---------- data ---------- */')[0]
DECLARATIONS = '\n'.join(line for line in SOURCE.splitlines() if line.startswith(
    ('const fin=', 'const dObj=', 'const md=', 'const esc=', 'const daysTo=', 'const addDays=', 'const wd=')))


def function_block(first, following):
    return SOURCE[SOURCE.index(first):SOURCE.index(following, SOURCE.index(first))]


RENDERERS = '\n'.join((
    function_block('function renderHero()', 'function renderToday()'),
    SOURCE[SOURCE.index('function nextEvents('):].splitlines()[0],
    function_block('function renderSoon()', '/* ---------- radar section ---------- */'),
    function_block('function renderCal()', '/* ---------- drawer ---------- */'),
    function_block('function openDrawer(', 'function closeDrawer()'),
))
HARNESS = r'''
const assert=require('node:assert/strict');
const TODAY='2026-11-04',WD='日一二三四五六',ASOF='2026-11-03',ASOFL='11/3 收盘';
const D={meta:{today:TODAY,generatedAt:'2026-11-04T01:54:00+08:00'}};
const CO=[],CP=[],IND=[],KEY_IND=[],TIGHT={},WK={mode:'none'},TOP={};
const byId={},ORDER=[],S={drawer:null,range:'6m'}; let drawerReturn=null;
const boxes={},$=id=>(boxes[id]??={innerHTML:'',textContent:'',hidden:false});
const IC=()=>'',ICON=new Proxy({},{get:()=>''});
const document={activeElement:null},requestAnimationFrame=()=>{};
const renderToday=()=>{},hideTip=()=>{},activateDrawer=()=>{},seg=()=>{},rangeComplete=()=>false;
const fmtPrice=()=>'',ud=()=>'',pct=()=>'',timeDetail=()=>'',mcapStr=()=>'',metricGap=()=>'';
const finDetail=()=>'',finLabel=()=>'',financialCell=()=>'',peLabel=()=>'',financialEvidence=()=>'';
const marketEvidence=()=>'',flashHTML=()=>'',sgBadges=()=>'';
const company=(id,mkt='美股',next='2026-11-03',zone='America/New_York')=>({
 id,name:id,short:id,code:id,ind:'test',mkt,next,perf:{k:'p0'},t:[],
 earnings:{status:'confirmed',source_url:'https://issuer.test/report',timezone:zone,time_note:'盘后发布'}});
const put=(...rows)=>{CO.push(...rows);for(const row of rows){byId[row.id]=row;ORDER.push(row.id)}};
Date.now=()=>{throw Error('Earnings dates must not use the viewer clock')};
'''


class EarningsTimezoneFrontendTests(unittest.TestCase):
    def run_js(self, assertions):
        self.assertIsNotNone(NODE, 'Node.js is required for calendar regressions')
        result = subprocess.run([NODE, '-e', HARNESS + '\n' + DECLARATIONS + '\n' + HELPERS
                                 + '\n' + RENDERERS + '\n' + assertions],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_beijing_midnight_does_not_expire_us_today(self):
        self.run_js(r'''
const us=company('US'),cn=company('CN','A股','2026-11-03','Asia/Shanghai');
assert.equal(issuerToday(us),'2026-11-03');assert.equal(issuerToday(cn),'2026-11-04');
assert.equal(issuerEventState(us),'confirmed');assert.equal(issuerEventCountdown(us),'今天');
assert.equal(issuerEventState(cn),'overdue');assert.match(issuerEventCountdown(cn),/已过 1 天/);
assert.equal(upcomingEarnings(us,14),true);assert.equal(upcomingEarnings(cn,14),false);
D.meta.generatedAt='2026-11-04T05:00:00Z';
assert.equal(issuerEventState(us),'overdue');assert.match(issuerEventCountdown(us),/已过 1 天/);
''')

    def test_issuer_timezone_overrides_market_default(self):
        self.run_js(r'''
D.meta.generatedAt='2026-11-04T06:30:00Z';
const ny=company('NY'),la=company('LA','美股','2026-11-03','America/Los_Angeles');
assert.equal(issuerToday(ny),'2026-11-04');assert.equal(issuerToday(la),'2026-11-03');
assert.equal(issuerEventState(ny),'overdue');assert.equal(issuerEventState(la),'confirmed');
''')

    def test_dst_midnight_and_repeated_hour_use_iana_rules(self):
        self.run_js(r'''
const us=company('US');
for(const [clock,day] of [
 ['2026-03-08T04:59:59Z','2026-03-07'],['2026-03-08T05:00:00Z','2026-03-08'],
 ['2026-03-08T06:59:59Z','2026-03-08'],['2026-03-08T07:00:00Z','2026-03-08'],
 ['2026-11-01T03:59:59Z','2026-10-31'],['2026-11-01T04:00:00Z','2026-11-01'],
 ['2026-11-01T05:30:00Z','2026-11-01'],['2026-11-01T06:30:00Z','2026-11-01']]){
 assert.equal(issuerToday(us,clock),day,clock);
}
''')

    def test_empty_and_invalid_zones_use_market_default_without_changing_evidence(self):
        self.run_js(r'''
for(const zone of ['',null,'Invalid/Timezone','+08:00']){
 const c=company('US','美股','2026-11-03',zone);
 assert.equal(issuerToday(c),'2026-11-03');assert.equal(earningsZone(c),'America/New_York');
 assert.equal(hasConfirmedEvent(c),true);assert.equal(c.earnings.timezone,zone);
}
const c=company('UNKNOWN','未知','2026-11-03','Invalid/Timezone');
assert.equal(issuerToday(c),null);assert.equal(issuerEventState(c),'unknown');
assert.match(issuerEventCountdown(c),/日期状态未确认/);assert.equal(upcomingEarnings(c),false);
assert.equal(hasConfirmedEvent(c),true);
''')

    def test_invalid_clocks_never_fall_back_to_beijing_or_viewer_clock(self):
        self.run_js(r'''
const c=company('US');
for(const clock of ['', '2026-11-04', '2026-11-04T01:54:00', '2026-02-30T12:00:00Z',
 '2026-11-04T24:00:00Z','2026-11-04T01:60:00Z','2026-11-04T01:00:60Z',
 '2026-11-04T01:00:00+24:00','2026-11-04T01:00:00+00:99', 'not-a-clock']){
 D.meta.generatedAt=clock;assert.equal(issuerToday(c),null,clock);
 assert.equal(issuerEventState(c),'unknown');assert.equal(upcomingEarnings(c,14),false);
 assert.doesNotMatch(eventTip(c),/已过/);
}
''')

    def test_absent_snapshot_clock_has_explicit_legacy_date_compatibility_only(self):
        self.run_js(r'''
const c=company('US');delete D.meta.generatedAt;
assert.equal(issuerToday(c),TODAY);assert.equal(issuerEventState(c),'overdue');
assert.equal(issuerToday(c,null,'2026-11-03'),'2026-11-03');
assert.equal(issuerToday(c,'bad','2026-11-03'),null);
assert.equal(eventState(c,'2026-11-03'),'confirmed');
assert.equal(eventCountdown('2026-11-03','2026-11-03'),'今天');
''')

    def test_two_week_boundary_is_inclusive_for_each_issuer(self):
        self.run_js(r'''
const us14=company('US14','美股','2026-11-17'),us15=company('US15','美股','2026-11-18');
const cn14=company('CN14','A股','2026-11-18','Asia/Shanghai');
assert.equal(upcomingEarnings(us14,14),true);assert.equal(upcomingEarnings(us15,14),false);
assert.equal(upcomingEarnings(cn14,14),true);
assert.equal(issuerEventCountdown(us14),'14 天后');assert.equal(issuerEventCountdown(cn14),'14 天后');
''')

    def test_missing_date_and_unconfirmed_source_keep_their_distinct_markers(self):
        self.run_js(r'''
const noDate=company('NO_DATE','美股',null),noSource=company('NO_SOURCE');
noSource.earnings.source_url='';
assert.equal(issuerEventState(noDate),'undated');assert.equal(issuerEventCountdown(noDate),'日期待定');
assert.equal(issuerEventState(noSource),'unverified');assert.equal(issuerEventLabel(noSource),'预估');
noSource.earnings.source_url='http://issuer.test/report';assert.equal(hasConfirmedEvent(noSource),false);
assert.equal(upcomingEarnings({...noSource,next:'2026-02-30'}),false);
assert.equal(issuerEventState({...noSource,next:'2026-02-30'}),'unknown');
''')

    def test_hero_kpi_soon_list_and_validation_windows_include_local_today(self):
        self.run_js(r'''
put(company('US_TODAY'),company('CN_PAST','A股','2026-11-03','Asia/Shanghai'),
 company('US14','美股','2026-11-17'),company('US15','美股','2026-11-18'),
 company('CN14','A股','2026-11-18','Asia/Shanghai'));
renderHero();renderSoon();
assert.match(boxes['#kpis'].innerHTML,/data-count="3">3<\/span><span class="l">两周内财报/);
assert.match(boxes['#soonCard'].innerHTML,/当地今天起14天 · 3 家/);
assert.match(boxes['#soonCard'].innerHTML,/US_TODAY/);assert.doesNotMatch(boxes['#soonCard'].innerHTML,/CN_PAST|US15/);
assert.deepEqual(nextEvents(CO,9).flatMap(e=>e.cs.map(c=>c.id)),['US_TODAY','US14','US15','CN14']);
''')

    def test_calendar_same_date_mixed_timezones_does_not_share_wrong_countdown(self):
        self.run_js(r'''
const us=company('US_TODAY'),cn=company('CN_PAST','A股','2026-11-03','Asia/Shanghai');put(us,cn);
renderCal();assert.match(boxes['#calSub'].textContent,/北京时间 11\/4/);
assert.match(boxes['#calSub'].textContent,/官方确认 1 · 预估 0 · 待更新 1/);
assert.match(boxes['#cal'].innerHTML,/<div class="cal-cd">按公司所在地<\/div>/);
assert.match(eventTip(us),/美东时间 盘后发布 · 今天/);
assert.doesNotMatch(eventTip(us),/已过/);assert.match(eventTip(cn),/已过 1 天/);
assert.equal(groupedEarningsCountdown([us]),'今天');
''')

    def test_actual_drawer_and_token_buttons_agree_with_calendar(self):
        self.run_js(r'''
const c=company('US_TODAY');put(c);openDrawer(c.id);
assert.match(boxes['#drawer'].innerHTML,/<span class="cd">今天<\/span>/);
assert.doesNotMatch(boxes['#drawer'].innerHTML,/已过 1 天/);
assert.match(earningsHTML('{{earnings:US_TODAY}}'),/11\/3 · 官方确认/);
assert.match(earningsHTML('{{earnings:UNKNOWN}}'),/日期待定/);
D.meta.generatedAt='2026-11-04T05:00:00Z';openDrawer(c.id);
assert.match(boxes['#drawer'].innerHTML,/<span class="cd">已过 1 天 · 待更新<\/span>/);
assert.match(earningsHTML('{{earnings:US_TODAY}}'),/11\/3 · 待更新/);
assert.equal(c.next,'2026-11-03');assert.equal(c.earnings.status,'confirmed');
''')

    def test_python_and_browser_issuer_dates_match_fixed_boundary_matrix(self):
        cases = [
            ('2026-11-03T16:30:00Z', '美股', '', '2026-11-03'),
            ('2026-11-03T16:30:00Z', 'A股', '', '2026-11-04'),
            ('2026-11-03T16:30:00Z', '港股', '', '2026-11-04'),
            ('2026-11-03T16:30:00Z', '台股', '', '2026-11-04'),
            ('2026-11-03T16:30:00Z', '韩股', '', '2026-11-04'),
            ('2026-11-03T16:30:00Z', '日股', '', '2026-11-04'),
            ('2026-11-03T16:30:00Z', '欧股', '', '2026-11-03'),
            ('2026-11-04T06:30:00Z', '美股', 'America/Los_Angeles', '2026-11-03'),
            ('2026-11-04T06:30:00Z', '美股', 'US/Eastern', '2026-11-04'),
            ('2026-03-08T04:59:59Z', '美股', '', '2026-03-07'),
            ('2026-03-08T05:00:00Z', '美股', '', '2026-03-08'),
            ('2026-11-01T05:30:00Z', '美股', '', '2026-11-01'),
            ('2026-11-01T06:30:00Z', '美股', '', '2026-11-01'),
            ('2026-12-31T16:30:00Z', '日股', '', '2027-01-01'),
            ('2026-12-31T16:30:00Z', '欧股', 'Europe/Berlin', '2026-12-31'),
            ('2026-11-03T16:30:00Z', '美股', 'Invalid/Timezone', '2026-11-03'),
            ('2026-11-03T16:30:00Z', '未知', 'Invalid/Timezone', None),
            ('2026-11-03T16:30:00', '美股', '', None),
            ('2026-02-30T12:00:00Z', '美股', '', None),
        ]
        for clock, market, zone, expected in cases:
            with self.subTest(clock=clock, market=market, zone=zone):
                result = issuer_today(clock, market, zone)
                self.assertEqual(result.isoformat() if result else None, expected)
        self.run_js('const cases=' + json.dumps(cases) + ';' + r'''
for(const [clock,market,zone,expected] of cases){
 assert.equal(issuerToday(company('C',market,'2026-11-03',zone),clock),expected,JSON.stringify([clock,market,zone]));
}
''')

    def test_all_supported_market_defaults_use_same_snapshot_instant(self):
        self.run_js(r'''
D.meta.generatedAt='2026-11-03T16:30:00Z';
for(const market of ['A股','港股','台股','韩股','日股'])assert.equal(issuerToday(company(market,market,'2026-11-04','')),'2026-11-04');
for(const market of ['美股','欧股'])assert.equal(issuerToday(company(market,market,'2026-11-03','')),'2026-11-03');
''')


if __name__ == '__main__':
    unittest.main()
