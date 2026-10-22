"""Regression contracts for dated claims and independent drawdown counting."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'radar/scripts'))
import schema


class ContentDisplayTests(unittest.TestCase):
    def run_js(self, assertions):
        source = (ROOT/'radar/site/app.js').read_text(encoding='utf-8')
        helpers = source.split('/* ---------- research and calendar validity ---------- */')[1].split('/* ---------- data ---------- */')[0]
        declarations = '\n'.join(line for line in source.splitlines()
                                 if line.startswith(('const fin=', 'const dObj=', 'const md=', 'const esc=')))
        script = "const assert=require('node:assert/strict');const TODAY='2026-10-21';\n"+declarations+'\n'+helpers+'\n'+assertions
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rebounding_company_still_counts_as_deep_drawdown(self):
        self.run_js("""
          const rows=[{r20:.0611,dd52:-.538},{r20:-.2,dd52:-.4},{dd52:-.3999},
                      {dd52:null},{dd52:undefined},{dd52:NaN},{dd52:'-.5'}];
          assert.equal(rows.filter(deepDrawdown).length,2);
          assert.equal(deepDrawdown({r20:1,dd52:-.5}),true);
        """)

    def test_week_boundary_and_legacy_opinion_remain_stale(self):
        self.run_js("""
          assert.equal(isoWeek('2026-10-21'),'2026-W43');
          assert.equal(isoWeek('2021-01-01'),'2020-W53');
          const legacy={review:{status:'verified',verified_at:'2026-10-21'}};
          assert.equal(judgmentOf(legacy).label,'stale');
          assert.deepEqual(judgmentOf(legacy).reasons,['legacy_data']);
          assert.equal(reasonText('legacy_data'),'旧版数据，无研判信息');
          assert.equal(legacy.review.verified_at,'2026-10-21');
        """)

    def test_judgment_reasons_and_provenance_preserve_dates(self):
        self.run_js(r"""
          const j={label:'stale',date:'2026-10-17',validUntil:'2026-10-19',reasons:['not_current_week','expired'],sources:[]};
          const html=provenanceLine(j,'weekly','','stale');
          assert.match(html,/待更新/);assert.match(html,/10\/17 研判/);
          assert.match(html,/10\/19，已过期/);assert.match(html,/显示上次结论/);
          assert.match(html,/tabindex="0"/);assert.match(html,/aria-label=/);
          assert.equal(j.date,'2026-10-17');
          assert.match(reasonText('future_judgment_date'),/未来/);
          assert.match(reasonText('missing_source'),/缺来源/);
        """)

    def test_calendar_distinguishes_unverified_estimated_confirmed_and_past(self):
        self.run_js("""
          const c={next:'2026-10-28',earnings:{status:'confirmed',source_url:'https://issuer.test/invitation',published_at:'2026-10-21',verified_at:'2026-10-21',timezone:'Asia/Seoul'}};
          assert.equal(eventState(c),'confirmed');
          assert.equal(eventState({...c,earnings:{status:'confirmed'}}),'unverified');
          assert.equal(eventLabel({...c,earnings:{...c.earnings,status:'estimated'}}),'预估');
          assert.equal(eventLabel({...c,earnings:{status:'confirmed',source_url:'http://issuer.test/invitation'}}),'预估');
          assert.equal(eventState(c,'2026-10-20'),'confirmed');
          assert.equal(eventState(c,'2026-10-29'),'overdue');
          assert.equal(eventState({...c,next:null}),'undated');
          assert.deepEqual(eventCounts([c,{next:'2026-10-30'},{next:'2026-10-20'},{}]),{confirmed:1,estimated:0,unverified:2,overdue:0,undated:1});
          assert.match(eventCountdown('2026-10-20'),/已过 1 天.*待更新/);
        """)

    def test_every_referenced_surface_follows_one_date_and_status(self):
        self.run_js(r"""
          const co={SKH:{next:'2026-10-28',earnings:{status:'confirmed',source_url:'https://issuer.test/invitation',published_at:'2026-10-21',verified_at:'2026-10-21',timezone:'Asia/Seoul'}}};
          const templates=['海力士Q3（{{earnings:SKH}}）','{{earnings:SKH}}发财报'];
          for(const t of templates)assert.match(earningsText(t,co),/10\/28 · 官方确认/);
          co.SKH.next='2026-10-30';co.SKH.earnings={};
          for(const t of templates)assert.match(earningsText(t,co),/10\/30 · 预估/);
          assert.equal(earningsText('{{earnings:UNKNOWN}}',co),'日期待定');
        """)


class ContentSchemaTests(unittest.TestCase):
    today = dt.date(2026, 10, 21)

    def test_missing_review_never_receives_a_verification_date(self):
        rep = schema.Report()
        value = schema._review(rep, 'test', {}, self.today)
        self.assertEqual(value['status'], 'unverified')
        self.assertEqual(value['verified_at'], '')
        self.assertFalse(rep.errors)

    def test_review_requires_evidence_and_a_valid_review_window(self):
        for raw in ({'status':'verified'}, {'status':'verified','verified_at':'2026-10-20','valid_until':'2026-10-19','source_url':'https://issuer.test/report','note':'Evidence'}):
            rep = schema.Report()
            schema._review(rep, 'test', {'review':raw}, self.today)
            self.assertTrue(rep.errors)

    def test_confirmation_cannot_be_granted_by_a_date_alone(self):
        rep = schema.Report()
        schema._earnings(rep, 'test', {'earnings':{'status':'confirmed'}}, '2026-10-28', self.today)
        self.assertTrue(rep.errors)

    def test_invalid_source_and_reversed_publication_dates_are_rejected(self):
        base={'status':'confirmed','source_url':'https://issuer.test/invitation','published_at':'2026-10-21','verified_at':'2026-10-21','timezone':'Asia/Seoul'}
        for change in ({'source_url':'javascript:alert(1)'},{'published_at':'2026-10-22'},{'timezone':''}):
            rep = schema.Report()
            schema._earnings(rep, 'test', {'earnings':{**base,**change}}, '2026-10-28', self.today)
            self.assertTrue(rep.errors)

    def test_live_config_only_promotes_the_officially_checked_event(self):
        data, rep = schema.load_and_validate(ROOT/'radar', ROOT, self.today)
        self.assertFalse(rep.errors, rep.errors)
        confirmed = [c for c in data['companies'] if c['earnings']['status']=='confirmed']
        self.assertEqual([c['id'] for c in confirmed], ['SKH'])
        self.assertEqual(confirmed[0]['next'], '2026-10-28')
        self.assertEqual(data['config']['weekly']['week'], '2026-W42')
        self.assertTrue(all(c['review']['status']=='unverified' for c in data['industries']+data['chokepoints']))
        self.assertEqual(data['config']['weekly']['review']['verified_at'], '')

    def test_future_source_is_unavailable_to_historical_snapshots(self):
        data, rep = schema.load_and_validate(ROOT/'radar', ROOT, dt.date(2026,10,17))
        self.assertFalse(rep.errors, rep.errors)
        skh = next(c for c in data['companies'] if c['id']=='SKH')
        self.assertEqual(skh['earnings']['status'], 'unverified')
        self.assertEqual(skh['earnings']['availability'], 'future_evidence')

    def test_build_carries_independent_review_and_calendar_metadata(self):
        from test_review_regressions import complete_dataset
        from test_integrity import build, NOW
        data, market = complete_dataset()
        D = build.assemble(data, market, market, NOW)[0]
        self.assertEqual(D['meta']['weekly']['review'], data['config']['weekly']['review'])
        self.assertEqual(D['companies'][0]['earnings'], data['companies'][0]['earnings'])
        self.assertEqual(D['meta']['weekly']['review']['verified_at'], '')


if __name__=='__main__':
    unittest.main()
