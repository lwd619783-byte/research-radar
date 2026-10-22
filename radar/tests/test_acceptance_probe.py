"""Offline transport, redaction, scope and manual-workflow contracts."""
import datetime as dt
import io
import os
import subprocess
import tempfile
import json
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'radar/scripts'))
import acceptance_probe as probe
from test_integrity import dataset,record,bars,NOW


class Response:
    status=200
    def __init__(self,body=b'{}'): self.body=body
    def read(self,n): return self.body[:n]
    def __enter__(self): return self
    def __exit__(self,*args): pass


class Opener:
    def __init__(self,*results): self.results=list(results); self.calls=0
    def open(self,url,timeout):
        self.calls+=1
        item=self.results.pop(0)
        if isinstance(item,Exception): raise item
        return item


URL='https://query1.finance.yahoo.com/v8/finance/chart/TEST'


class TransportTests(unittest.TestCase):
    def test_allowlist_blocks_unknown_hosts_paths_and_credentials(self):
        for url in ('http://query1.finance.yahoo.com/v8/finance/chart/T','https://example.test/',
                    'https://query2.finance.yahoo.com/v8/finance/chart/T','https://query1.finance.yahoo.com/private',
                    'https://user:secret@query1.finance.yahoo.com/v8/finance/chart/T',
                    'https://query1.finance.yahoo.com:8443/v8/finance/chart/T'):
            with self.subTest(url=url),self.assertRaises(probe.StopProbe): probe.route(url)

    def test_401_403_451_stop_the_corresponding_lane(self):
        for code in (401,403,451):
            with self.subTest(code=code):
                budget=probe.Budget()
                h=probe.ProbeHttp(budget,'yahoo')
                h.op=Opener(urllib.error.HTTPError(URL,code,'secret-server-text',{},None))
                with self.assertRaises(probe.StopProbe): h.get(URL)
                with self.assertRaises(probe.StopProbe): h.get(URL+'2')
                self.assertEqual(h.op.calls,1)
                self.assertEqual(budget.count,1)
                self.assertIn('yahoo-chart',budget.denied)

    def test_429_retries_once_with_bounded_backoff(self):
        h=probe.ProbeHttp(probe.Budget(),'yahoo')
        h.op=Opener(urllib.error.HTTPError(URL,429,'secret',{'Retry-After':'5'},None),Response())
        with patch.object(probe.time,'sleep') as sleep:
            self.assertEqual(h.json(URL),{})
            sleep.assert_called_once_with(5.)
        self.assertEqual(h.op.calls,2)

    def test_large_retry_after_and_500_are_not_retried(self):
        for code in (429,500):
            h=probe.ProbeHttp(probe.Budget(),'yahoo')
            h.op=Opener(urllib.error.HTTPError(URL,code,'secret',{'Retry-After':'120'},None))
            with self.assertRaises(probe.StopProbe): h.get(URL)
            self.assertEqual(h.op.calls,1)


    def test_http_date_retry_after_is_not_shortened(self):
        h=probe.ProbeHttp(probe.Budget(),'yahoo')
        h.op=Opener(urllib.error.HTTPError(URL,429,'secret',{'Retry-After':'Wed, 21 Oct 2026 07:28:00 GMT'},None))
        with patch.object(probe.time,'sleep') as sleep,self.assertRaises(probe.StopProbe): h.get(URL)
        sleep.assert_not_called()
        self.assertEqual(h.op.calls,1)

    def test_request_and_wall_clock_budgets(self):
        h=probe.ProbeHttp(probe.Budget(limit=1),'yahoo');h.op=Opener(Response())
        h.get(URL)
        with self.assertRaises(probe.StopProbe): h.get(URL)
        budget=probe.Budget(seconds=-1)
        with self.assertRaises(probe.StopProbe): budget.take('yahoo-chart')
        self.assertEqual(budget.count,0)

    def test_no_redirects(self):
        with self.assertRaises(probe.StopProbe):
            probe.NoRedirect().redirect_request(None,None,302,'',{},'https://example.test/')

    def test_body_limit(self):
        h=probe.ProbeHttp(probe.Budget(),'yahoo'); h.op=Opener(Response(b'x'*20))
        with patch.object(probe,'MAX_BODY',10),self.assertRaises(probe.StopProbe): h.get(URL)

    def test_cookie_seed_404_is_allowed_but_403_stops_crumb(self):
        h=probe.ProbeHttp(probe.Budget(),'yahoo')
        h.op=Opener(urllib.error.HTTPError('https://fc.yahoo.com',404,'not-found',{},None),Response(b'synthetic-crumb'))
        self.assertEqual(h.crumb(),'synthetic-crumb')
        self.assertNotIn('synthetic-crumb',json.dumps(h.events))
        self.assertTrue(all('sha256' not in event for event in h.events))
        other=probe.ProbeHttp(probe.Budget(),'yahoo')
        other.op=Opener(urllib.error.HTTPError('https://fc.yahoo.com',403,'denied',{},None))
        with self.assertRaises(probe.StopProbe): other.crumb()
        self.assertEqual(other.op.calls,1)

    def test_query_and_crumb_never_appear_in_receipts(self):
        h=probe.ProbeHttp(probe.Budget(),'yahoo');h.op=Opener(Response(b'{"quoteResponse":{"result":[]}}'))
        h.yahoo('/v7/finance/quote?symbols=T&crumb=DO_NOT_LEAK')
        serialized=json.dumps({'events':h.events,'batches':h.batches})
        self.assertNotIn('DO_NOT_LEAK',serialized)
        self.assertNotIn('?symbols',serialized)
        self.assertEqual(h.batches[0]['requested'],1)


class QualityTests(unittest.TestCase):
    def test_exact_inventory_from_frozen_config(self):
        data,_=dataset();companies,tx,fx=probe.inventory(data)
        self.assertEqual(len(companies),42)
        self.assertEqual(sum(c['mkt']=='A股' for c in tx),22)
        self.assertEqual(sum(c['mkt']=='港股' for c in tx),2)
        self.assertEqual(len(data['config']['indices']),8)
        self.assertEqual(sum(bool(x.get('tencent')) for x in data['config']['indices']),5)
        self.assertEqual(fx,['CNY','EUR','HKD','JPY','KRW','TWD'])

    def test_200_empty_payload_is_not_quality_success(self):
        def fetch(h):
            h.op=Opener(Response())
            h.json(URL)
            return {}
        row,_=probe.inspect('index-yahoo','T','yahoo',probe.Budget(),fetch,probe.index_quality)
        self.assertTrue(row['connection']);self.assertTrue(row['parse'])
        self.assertFalse(row['quality']);self.assertFalse(row['publicationGate'])

    def test_server_error_message_and_local_path_are_not_serialized(self):
        def fetch(h): raise RuntimeError('crumb=SECRET C:/private/research.md')
        row,_=probe.inspect('index-yahoo','T','yahoo',probe.Budget(),fetch,probe.index_quality)
        self.assertEqual(row['failure'],'RuntimeError')
        self.assertNotIn('SECRET',json.dumps(row));self.assertNotIn('private',json.dumps(row))

    def test_tencent_unknown_is_not_closed(self):
        h=probe.ProbeHttp(probe.Budget(),'tencent')
        value=record(price=100,chg=.1,date=dt.date.today().isoformat(),phase='unknown')
        fields,details,gate=probe.index_quality(value,h)
        self.assertFalse(gate);self.assertEqual(details['phase'],'unknown')

    def test_fx_inverse_direction(self):
        h=probe.ProbeHttp(probe.Budget(),'yahoo')
        h.documents=[{'chart':{'result':[{'meta':{'regularMarketPrice':2.}}]}}]
        value=record(value=.5,asOf=NOW.date().isoformat(),rates=[[NOW.date().isoformat(),.5,2.]])
        self.assertTrue(probe.fx_quality(value,h,'EUR')[0]['directionVerified'])
        self.assertFalse(probe.fx_quality(value,h,'CNY')[0]['directionVerified'])

class CollectionTests(unittest.TestCase):
    def test_complete_failed_source_inventory_and_redaction_still_yields_blockers(self):
        data,_=dataset()
        for c in data['companies']: c['financial'] = {}
        # Every adapter fails; the complete diagnostic receipt must still be made.
        # This is intentionally synthetic and never opens a socket.
        secret=RuntimeError('crumb=DO_NOT_LEAK C:/private/research.md')
        with patch.object(probe.quotes,'yahoo_daily',side_effect=secret), \
             patch.object(probe.quotes,'tencent_daily',side_effect=secret), \
             patch.object(probe.quotes,'yahoo_quotes',side_effect=secret), \
             patch.object(probe.quotes,'index_quote',side_effect=secret), \
             patch.object(probe.quotes,'fx',side_effect=secret), \
             patch.object(probe.quotes,'monthly',side_effect=secret):
            rows,summary,session,gates=probe.collect(data,probe.Budget())
        expected={'company-yahoo-daily':42,'company-tencent-backup':24,'company-yahoo-quote':42,
                  'index-yahoo':8,'index-tencent':5,'fx':6,'ratio-tencent':2,'ratio-yahoo':2}
        self.assertEqual({k:v['planned'] for k,v in summary.items()},expected)
        self.assertEqual(len(rows),131)
        self.assertTrue(all(not r['publicationGate'] for r in rows))
        self.assertEqual(session['failure'],'RuntimeError')
        self.assertEqual(session['expectedBatchSizes'],[40,2])
        self.assertEqual(gates['financialRequired'],42)
        self.assertEqual(gates['financialVerified'],0)
        self.assertTrue(gates['blockers'])
        receipt=json.dumps([rows,summary,session,gates],allow_nan=False)
        self.assertNotIn('DO_NOT_LEAK',receipt)
        self.assertNotIn('private/research',receipt)
        self.assertLess(len(receipt.encode()),probe.MAX_RECEIPT)


class WorkflowTests(unittest.TestCase):
    def workflow(self): return json.loads((ROOT/'.github/workflows/radar-interface-acceptance.yml').read_text('utf-8'))

    def test_manual_only_one_standard_linux_job(self):
        w=self.workflow();self.assertEqual(set(w['on']),{'workflow_dispatch'})
        self.assertEqual(w['permissions'],{'contents':'read'});self.assertEqual(len(w['jobs']),1)
        job=w['jobs']['acceptance'];self.assertEqual(job['runs-on'],'ubuntu-24.04')
        self.assertEqual(job['timeout-minutes'],20);self.assertIn('github.run_attempt == 1',job['if'])
        self.assertNotIn('secrets.',json.dumps(w))

    def test_current_branch_exact_sha_and_zero_cost_gate_before_runner(self):
        w=self.workflow();job=w['jobs']['acceptance']
        self.assertEqual(job['if'],
            "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/fix/radar-truthfulness-2026-10-18' && github.run_attempt == 1 && inputs.zero_cost_verified == true && inputs.reviewed_sha == github.sha")
        cost=w['on']['workflow_dispatch']['inputs']['zero_cost_verified']
        self.assertEqual(cost['type'],'boolean');self.assertTrue(cost['required']);self.assertIs(cost['default'],False)
        checkout=next(s for s in job['steps'] if s.get('uses','').startswith('actions/checkout@'))
        self.assertEqual(checkout['with']['ref'],'${{ github.sha }}')
        self.assertEqual(probe.MAX_REQUESTS,240)
        self.assertEqual(probe.MAX_RECEIPT,512*1024)

    def test_actual_shell_guard_rejects_wrong_branch_sha_cost_and_reruns(self):
        guard=self.workflow()['jobs']['acceptance']['steps'][0]
        self.assertEqual(guard['env'],{'REVIEWED_SHA':'${{ inputs.reviewed_sha }}','ZERO_COST_VERIFIED':'${{ inputs.zero_cost_verified }}'})
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'GITHUB_EVENT_NAME':'workflow_dispatch',
             'GITHUB_REF':'refs/heads/fix/radar-truthfulness-2026-10-18','GITHUB_RUN_ATTEMPT':'1',
             'GITHUB_SHA':'a'*40,'REVIEWED_SHA':'a'*40,'ZERO_COST_VERIFIED':'true'}
        def run(change):
            return subprocess.run(['bash','-c',guard['run']],env={**env,**change},capture_output=True).returncode
        self.assertEqual(run({}),0)
        for change in ({'GITHUB_REF':'refs/heads/fix/radar-data-integrity'},
                       {'GITHUB_REF':'refs/heads/main'},{'GITHUB_EVENT_NAME':'push'},
                       {'GITHUB_RUN_ATTEMPT':'2'},{'ZERO_COST_VERIFIED':'false'},
                       {'ZERO_COST_VERIFIED':''},{'ZERO_COST_VERIFIED':'unknown'},
                       {'REVIEWED_SHA':'b'*40},{'REVIEWED_SHA':'a'*7},
                       {'REVIEWED_SHA':'A'*40},{'REVIEWED_SHA':'','GITHUB_SHA':''}):
            with self.subTest(change=change):self.assertNotEqual(run(change),0)
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'not-created'
            self.assertNotEqual(run({'REVIEWED_SHA':'$(touch '+str(marker)+')'}),0)
            self.assertFalse(marker.exists())

    def test_checkout_identity_is_verified_before_preflight_and_requests(self):
        steps=self.workflow()['jobs']['acceptance']['steps']
        verify=steps[2]
        self.assertEqual(verify['name'],'Verify checked-out HEAD equals reviewed execution SHA')
        self.assertIn('actions/checkout@',steps[1]['uses'])
        self.assertLess(2,next(i for i,s in enumerate(steps) if '--preflight' in s.get('run','')))
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        for reviewed,actual,success in ((head,head,True),('0'*40,head,False),(head,'0'*40,False)):
            with self.subTest(reviewed=reviewed,actual=actual):
                result=subprocess.run(['bash','-c',verify['run']],cwd=ROOT,
                    env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'REVIEWED_SHA':reviewed,'GITHUB_SHA':actual},capture_output=True)
                self.assertEqual(result.returncode==0,success)

    def test_fixed_official_actions_no_deployment(self):
        steps=self.workflow()['jobs']['acceptance']['steps']
        actions=[s['uses'] for s in steps if 'uses' in s]
        self.assertEqual(len(actions),3)
        for action in actions: self.assertRegex(action,r'^actions/(checkout|setup-python|upload-artifact)@[0-9a-f]{40}$')
        self.assertFalse(next(s for s in steps if s.get('uses','').startswith('actions/checkout@'))['with']['persist-credentials'])
        self.assertEqual(next(s for s in steps if s.get('uses','').startswith('actions/setup-python@'))['with']['python-version'],'3.12')

    def test_only_explicit_verified_bundle_uploaded_for_seven_days(self):
        steps=self.workflow()['jobs']['acceptance']['steps']
        artifact=next(s for s in steps if s.get('uses','').startswith('actions/upload-artifact@'))['with']
        self.assertEqual(artifact['path'].splitlines(), ['${{ runner.temp }}/radar-interface-acceptance/'+name for name in probe.bundle.FILES])
        verify=next(s for s in steps if s.get('id')=='archive_verify')
        self.assertIn('--verify-bundle',verify['run'])
        self.assertEqual(probe.bundle.MAX_BUNDLE,10_000_000)
        upload=next(s for s in steps if s.get('uses','').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['if'],"success() && steps.probe.outcome == 'success' && steps.archive_verify.outcome == 'success'")
        self.assertEqual(artifact['retention-days'],7)
        self.assertFalse(artifact['include-hidden-files'])
        self.assertLess(next(i for i,s in enumerate(steps) if '--preflight' in s.get('run','')),next(i for i,s in enumerate(steps) if s.get('id')=='probe'))


if __name__=='__main__': unittest.main()
