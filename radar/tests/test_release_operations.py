"""Deployment failures, stale baselines and incomparable observations stay visible."""
import copy
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'radar/scripts'))
import acceptance_bundle as bundle
import daily_changes as changes
import release_operations as ops


def sample(day='2026-10-21'):
    return {'meta': {'generatedAt': day+'T18:00+08:00', 'weekly': {'review': {'status': 'unverified'}},
                     'coverage': [{'kind': 'company', 'symbol': 'ABC', 'metric': 'pe', 'status': 'missing'}]},
            'industries': [], 'chokepoints': [],
            'companies': [{'id':'ABC','name':'Example','sym':'ABC','cur':'USD','price':9999,'pricePhase':'intraday',
                           'sc':[10,11], 'r1d':.02, 'ld':day,'metricAsOf':day,'next':None,'earnings':{},'period':'Q2',
                           'provenance':{'daily':{'phase':'closed','src':'yahoo','returnBasis':'yahoo-adjclose'},
                                         'financial':{'status':'verified','basis':'single_quarter','currency':'USD'}}}]}


class ChangeTests(unittest.TestCase):
    def test_first_release_has_unknown_baseline_not_zero_change(self):
        self.assertEqual(changes.summarize(sample(), [])['mode'], 'unavailable')

    def test_prefers_prior_day_and_same_day_uses_honest_label(self):
        old = changes.project(sample('2026-10-20'), {'productionSHA':'a'*40})
        same = changes.project(sample(), {})
        data = sample(); data['meta']['generatedAt']='2026-10-21T19:00+08:00'
        self.assertEqual(changes.summarize(data,[old,same])['baselineAt'],old['generatedAt'])
        self.assertEqual(changes.summarize(data,[same])['mode'],'previous_update')
        self.assertEqual(changes.summarize(data,[same])['sameDatePrices'],1)

    def test_new_day_uses_admitted_daily_return_not_intraday_or_raw_ratio(self):
        old=changes.project(sample('2026-10-20'),{})
        data=sample();data['companies'][0]['sc'][-1]=550
        result=changes.summarize(data,[old])
        self.assertEqual(result['prices'][0]['change'],.02)
        self.assertNotEqual(result['prices'][0]['change'],550/11-1)

    def test_missing_phase_currency_source_basis_are_not_compared(self):
        old=changes.project(sample('2026-10-20'),{})
        for mutate in (lambda c:c.update(cur='EUR'),lambda c:c.update(r1d=None),
                       lambda c:c['provenance']['daily'].update(src='tencent'),
                       lambda c:c['provenance']['daily'].update(phase='intraday'),
                       lambda c:c['provenance']['daily'].update(returnBasis=None)):
            data=sample();mutate(data['companies'][0]);result=changes.summarize(data,[old])
            self.assertEqual(result['prices'],[]);self.assertEqual(result['excludedPrices'],1)

    def test_missing_to_not_applicable_is_not_restoration(self):
        old=changes.project(sample('2026-10-20'),{})
        data=sample();data['meta']['coverage'][0]['status']='not_applicable'
        self.assertEqual(changes.summarize(data,[old])['restored'],[])
        data['meta']['coverage'][0]['status']='complete'
        self.assertEqual(len(changes.summarize(data,[old])['restored']),1)

    def test_unverified_calendar_and_new_financial_period_keep_status(self):
        old=changes.project(sample('2026-10-20'),{})
        data=sample();data['companies'][0].update(next='2026-10-28',period='Q3')
        data['companies'][0]['provenance']['financial']['status']='verified_partial'
        result=changes.summarize(data,[old])
        self.assertEqual(result['calendar'][0]['status'],'unverified')
        self.assertEqual(result['reports'][0]['status'],'verified_partial')
        self.assertEqual(result['pendingResearch'],1)

    def test_adding_default_unverified_metadata_is_not_a_calendar_change(self):
        old=changes.project(sample('2026-10-20'),{})
        data=sample();data['companies'][0]['earnings']={'status':'unverified','source_url':'','verified_at':''}
        self.assertEqual(changes.summarize(data,[old])['calendar'],[])

    def test_history_is_bounded_and_last_release_per_day_wins(self):
        days=[changes.project(sample('2026-10-'+str(i).zfill(2)),{}) for i in range(1,12)]
        newer=copy.deepcopy(days[-1]);newer['generatedAt']='2026-10-11T19:00+08:00'
        history=changes.history_with(newer,days)
        self.assertEqual(len(history),8);self.assertEqual(history[-1],newer)


class ReleaseTests(unittest.TestCase):
    def status(self, state='success', commit='a'*40, url=ops.DEPLOY_PREFIX+'Example123'):
        return {'sha':commit,'statuses':[{'context':'Vercel','state':state,'target_url':url,'updated_at':'2026-10-21T11:00:00Z'}]}

    def test_exact_sha_and_project_required_before_success(self):
        with self.assertRaisesRegex(ValueError,'sha_mismatch'):ops.checked_status(self.status(),'b'*40)
        with self.assertRaisesRegex(ValueError,'unexpected'):ops.checked_status(self.status(url='https://vercel.com/other/project/id'),'a'*40)
        self.assertEqual(ops.checked_status(self.status(),'a'*40)['state'],'success')
        self.assertEqual(ops.checked_status({'sha':'a'*40,'statuses':[]},'a'*40)['state'],'pending')

    def test_pending_timeout_and_vercel_failure_do_not_pass(self):
        with patch.object(ops,'status',return_value={'state':'failure'}):
            with self.assertRaisesRegex(ValueError,'failed'):ops.wait_deployment('a'*40)
        with patch.object(ops,'status',return_value={'state':'pending'}),patch.object(ops.time,'monotonic',side_effect=[0,301]):
            with self.assertRaisesRegex(ValueError,'timeout'):ops.wait_deployment('a'*40)

    def make_release(self, root):
        root.mkdir();(root/'public').mkdir()
        data=sample();info={'schemaVersion':1,'state':'current','sourceSHA':'a'*40,'runId':'123',
                            'dataSHA256':bundle.data_digest(data),'generatedAt':data['meta']['generatedAt'],'changes':{'mode':'unavailable'}}
        page='<script>const DATA='+json.dumps(data)+';</script>\n<script id="radar-operations">const OPERATIONS='+json.dumps(info)+';</script>'
        (root/'public/index.html').write_text(page,encoding='utf-8')
        (root/'public/robots.txt').write_text('User-agent: *\nDisallow: /\n',encoding='utf-8')
        (root/'public/version.json').write_bytes(bundle.encoded(info))
        (root/'history.json').write_bytes(bundle.encoded({'schemaVersion':1,'days':[]}))
        (root/'release.json').write_bytes(bundle.encoded({'schemaVersion':2,'sourceSHA':'a'*40,'runId':'123',
            'dataSHA256':bundle.data_digest(data),'blockers':[],'files':{},'historySHA256':bundle.digest((root/'history.json').read_bytes())}))
        ops.refresh_hashes(root)
        return data

    def test_recovery_preserves_data_dates_nulls_and_summary(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'baseline';data=self.make_release(root);dest=Path(t)/'failure'
            ops.failure_release(root,dest,'collect','456','b'*40)
            m,actual=ops.verify_files(dest);self.assertEqual(data,actual)
            info=json.loads((dest/'public/version.json').read_text('utf-8'))
            self.assertEqual(info['generatedAt'],data['meta']['generatedAt'])
            self.assertEqual(info['state'],'failed');self.assertEqual(info['failedStage'],'collect')
            self.assertEqual(m['runId'],'123');self.assertEqual(info['attemptRunId'],'456')

    def test_tampered_history_html_and_status_fail_closed(self):
        for name in ('history.json','public/index.html','public/version.json'):
            with tempfile.TemporaryDirectory() as t:
                root=Path(t)/'baseline';self.make_release(root)
                with (root/name).open('a') as f:f.write(' ')
                with self.assertRaisesRegex(ValueError,'hash_mismatch'):ops.verify_files(root)

    def test_failure_summary_and_artifact_are_written_even_when_recovery_unavailable(self):
        with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{'GITHUB_RUN_ID':'456','GITHUB_SHA':'a'*40,'GITHUB_STEP_SUMMARY':str(Path(t)/'summary.md')}):
            with contextlib.redirect_stdout(io.StringIO()):
                result=ops.finish(t,{'preflight':'failure','baseline':'success'},'')
            self.assertEqual(result['state'],'failed');self.assertEqual(result['failedStage'],'preflight')
            self.assertEqual(result['recovery']['state'],'unavailable')
            self.assertTrue((Path(t)/'release-result.json').is_file())

    def test_vercel_build_checks_source_hashes_and_emits_exact_runtime_commit(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'release';self.make_release(root)
            env=os.environ|{'VERCEL_ENV':'production','VERCEL_GIT_COMMIT_REF':'production','VERCEL_GIT_COMMIT_SHA':'c'*40}
            p=subprocess.run(['node',str(ROOT/'radar/scripts/verify-release.cjs')],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads((root/'public/version.json').read_text())['productionSHA'],'c'*40)


class BrowserHelpersTests(unittest.TestCase):
    def test_safe_links_weekend_deadline_and_version_contract(self):
        source=(ROOT/'radar/site/app.js').read_text('utf-8')
        helpers=source.split('/* ---------- release and evidence helpers ---------- */')[1].split('/* ---------- data ---------- */')[0]
        script="const assert=require('node:assert/strict');\n"+helpers+"""
        for(const u of ['javascript:alert(1)','https://user:password@example.com','http://example.com','/private'])assert.equal(safeSourceUrl(u),'');
        assert.equal(safeSourceUrl('https://issuer.example/report'),'https://issuer.example/report');
        assert.equal(providerUrl('ABC','unknown'), '');
        assert.match(providerUrl('HSTECH.HK','tencent'), /hkHSTECH/);
        const schedule={nextRunAt:'2026-10-26T06:50+08:00',lateAfterMinutes:90};
        assert.equal(scheduledDue('2026-10-24T08:00+08:00',Date.parse('2026-10-25T23:00+08:00'),schedule),false);
        assert.equal(scheduledDue('2026-10-24T08:00+08:00',Date.parse('2026-10-26T08:20+08:00'),schedule),false);
        assert.equal(scheduledDue('2026-10-24T08:00+08:00',Date.parse('2026-10-26T08:21+08:00'),schedule),true);
        assert.equal(scheduledDue('2026-10-24T08:00+08:00',Date.parse('2026-10-26T13:16+08:00'),{}),false);
        assert.equal(validVersion({schemaVersion:1,state:'current',dataSHA256:'a'.repeat(64),sourceSHA:'b'.repeat(40),runId:'123'}),true);
        assert.equal(validVersion({state:'success'}),false);
        """
        p=subprocess.run(['node','-e',script],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)


if __name__=='__main__':unittest.main()
