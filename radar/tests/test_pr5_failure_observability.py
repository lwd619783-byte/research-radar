"""Exercise actual CLI failure stages and the production diagnostic export boundary."""
import contextlib
import datetime as dt
import hashlib
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
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import production_collect as collector
import live_notion_dry_run as live
import release_operations as operations
import test_release_operations as release_tests
from notion_fixtures import FixtureSet, FakeTransport
from notion_fixture_market import fixture_market
from research_snapshot import ResearchAbort

SECRET = 'ntn_FAILURE_OBSERVABILITY_SENTINEL_NEVER_REAL'
CLOCK = dt.datetime.fromisoformat('2026-10-21T18:15:00+08:00')
BLOCKER = 'mixed_or_missing_market_dates_need_label_approval'


class FailureObservabilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
            'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH,
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a' * 40}
        guard = patch('socket.socket.connect', side_effect=AssertionError('no network'))
        guard.start(); self.addCleanup(guard.stop)

    def cli(self, name='run', *, market=fixture_market, fail=None, baseline=None, mutations=()):
        root = self.root / name
        fixtures = FixtureSet(root / 'fixtures'); transport = FakeTransport(fixtures)
        fixtures.mutate(mutations)
        original = collector.collect
        def injected(**kwargs):
            return original(**kwargs, transport=transport, market_collect=market,
                clock=lambda: CLOCK, sleep=transport.sleep, pace=transport.pace)
        text = io.StringIO()
        args = ['--out', str(root / 'out/receipt.json'), '--work', str(root / 'work'), '--live-dry-run']
        if baseline:
            args += ['--baseline', str(baseline)]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(collector.os, 'environ', {**self.env, 'NOTION_TOKEN': SECRET}))
            stack.enter_context(patch.object(collector, 'collect', side_effect=injected))
            stack.enter_context(contextlib.redirect_stdout(text))
            stack.enter_context(contextlib.redirect_stderr(text))
            if fail:
                stack.enter_context(patch.object(*fail, side_effect=RuntimeError(SECRET)))
            status = collector.main(args)
        diagnostic = json.loads((root / 'work/diagnostic.json').read_text('utf-8'))
        self.stdout = text.getvalue()
        self.assertNotIn(SECRET, text.getvalue() + json.dumps(diagnostic))
        self.assertFalse((root / 'out').exists())
        return status, diagnostic, root

    def test_real_cli_reports_static_stage_for_each_pipeline_boundary(self):
        failures = [
            (collector, 'admit', 'admission'),
            (collector.build, 'research_config', 'research_config'),
            (collector.build, 'load_notion_contract', 'notion_contract'),
            (collector, 'baseline_snapshot', 'baseline_snapshot'),
            (collector, 'fetch_all', 'notion_fetch'),
            (collector, 'sanitize_fetch', 'notion_sanitize'),
            (collector, 'normalize', 'notion_normalize'),
            (collector.build, 'load_and_validate', 'market_config'),
            (collector.build, 'apply_research', 'research_apply'),
            (collector.build, 'release_blockers', 'release_gates'),
            (collector, 'step_summary', 'summary'),
            (collector.bundle, 'write_bundle', 'bundle_write'),
        ]
        for index, (owner, method, stage) in enumerate(failures):
            with self.subTest(stage=stage):
                status, diagnostic, _ = self.cli(str(index), fail=(owner, method))
                self.assertEqual(status, 1)
                self.assertEqual(diagnostic['code'], 'collection_failed')
                self.assertEqual(diagnostic['stage'], stage)

    def test_known_collect_error_has_fixed_code_without_calling_str(self):
        class HostileError(collector.CollectError):
            def __str__(self):
                raise AssertionError('exception text must never be evaluated')
        def market(*args, **kwargs):
            raise HostileError('invalid_baseline_snapshot')
        status, diagnostic, _ = self.cli(market=market)
        self.assertEqual(status, 2)
        self.assertEqual(diagnostic['code'], 'invalid_baseline_snapshot')
        self.assertEqual(diagnostic['stage'], 'market_collect')

    def test_production_market_failure_keeps_budget_count_and_calendar_policy(self):
        def market(config, budget, **kwargs):
            self.assertIs(kwargs['calendar_policy'], True)
            budget.take('yahoo-chart'); budget.take('yahoo-chart')
            raise ResearchAbort('quotes_coverage_low')
        with patch.object(collector.probe, 'collect', side_effect=market):
            status, diagnostic, _ = self.cli(market=None)
        self.assertEqual(status, 2)
        self.assertEqual(diagnostic['counts']['marketRequests'], 2)
        self.assertIs(diagnostic['calendarPolicy'], True)

    def test_failed_collect_diagnostic_export_keeps_old_data_and_failure_status(self):
        run = self.root/'run'; run.mkdir()
        baseline = run/'radar-baseline'
        old = release_tests.ReleaseTests().make_release(baseline)
        before = {p.relative_to(baseline).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in baseline.rglob('*') if p.is_file()}
        def market(*args, **kwargs):
            raise ResearchAbort(BLOCKER)
        status, _, root = self.cli(baseline=baseline, market=market)
        self.assertEqual(status, 2)
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '456', 'GITHUB_SHA': 'b'*40,
                'GITHUB_STEP_SUMMARY': str(root/'summary.md')}), \
             patch.object(operations, 'publish', return_value='c'*40), \
             patch.object(operations, 'wait_deployment', return_value={'state':'success'}), \
             contextlib.redirect_stdout(io.StringIO()):
            result = operations.finish(root, {'baseline':'success','preflight':'success','collect':'failure',
                'prepare':'skipped','publish':'skipped'}, '')
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['failedStage'], 'collect')
        _, retained = operations.verify_files(root/'radar-recovery')
        self.assertEqual(retained, old)
        self.assertEqual(json.loads((root/'radar-recovery/public/version.json').read_text('utf-8'))['state'], 'failed')
        after = {p.relative_to(baseline).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in baseline.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.export(root/'work', root/'artifact')
        self.assertFalse((root/'out').exists())

    def test_finish_failure_artifact_never_formats_exception_and_retains_old_snapshot(self):
        class HostileError(RuntimeError):
            def __str__(self):
                raise AssertionError('exception formatting is forbidden')
        baseline = self.root/'radar-baseline'
        old = release_tests.ReleaseTests().make_release(baseline)
        before = {p.relative_to(baseline).as_posix(): p.read_bytes() for p in baseline.rglob('*') if p.is_file()}
        with patch.dict(os.environ, {'GITHUB_RUN_ID':'456','GITHUB_SHA':'b'*40,
                'GITHUB_STEP_SUMMARY':str(self.root/'summary.md')}), \
             patch.object(operations, 'wait_deployment', side_effect=HostileError(SECRET)), \
             patch.object(operations, 'publish', side_effect=HostileError(SECRET)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            result = operations.finish(self.root, {k:'success' for k in
                ('baseline','preflight','collect','prepare','publish')}, 'c'*40)
        self.assertEqual(result['state'],'failed')
        self.assertEqual(result['failedStage'],'deployment')
        self.assertEqual(result['reason'],'deployment_failed')
        self.assertEqual(result['recovery'],{'state':'unavailable','reason':'recovery_failed'})
        self.assertNotIn(SECRET, output.getvalue() + (self.root/'release-result.json').read_text('utf-8')
                         + (self.root/'summary.md').read_text('utf-8'))
        _, retained=operations.verify_files(self.root/'radar-recovery')
        self.assertEqual(retained,old)
        self.assertEqual(before,{p.relative_to(baseline).as_posix():p.read_bytes()
            for p in baseline.rglob('*') if p.is_file()})

    def test_unknown_exception_and_unknown_controlled_code_never_echo_payload(self):
        for index, error in enumerate((RuntimeError(SECRET), collector.CollectError(SECRET), ResearchAbort(SECRET))):
            def market(*args, **kwargs):
                raise error
            status, diagnostic, _ = self.cli(str(index), market=market)
            self.assertEqual(status, 1 if index == 0 else 2)
            self.assertEqual(diagnostic['code'], 'collection_failed')
            self.assertEqual(diagnostic['stage'], 'market_collect')

    def test_research_abort_retains_all_known_codes_and_only_safe_table(self):
        def market(*args, **kwargs):
            raise ResearchAbort('no_last_good', codes=['notion_timeout', BLOCKER, SECRET],
                detail={'table': 'companies', 'raw': SECRET})
        _, diagnostic, _ = self.cli(market=market)
        self.assertEqual(diagnostic['code'], 'no_last_good')
        self.assertEqual(set(diagnostic['blockers']), {'no_last_good', 'notion_timeout', BLOCKER})
        self.assertEqual(diagnostic['table'], 'companies')

    def test_notion_fetch_error_before_handoff_retains_http_primitives(self):
        def reject(raw, *args, **kwargs):
            raw['tables']['companies']['error'] = {'code': 'notion_server_error', 'http_status': 503,
                'notion_code': 'service_unavailable', 'body': SECRET, 'headers': {'Authorization': SECRET}}
            raise ResearchAbort('no_last_good', codes=['notion_server_error'])
        # Fetch errors must be captured before sanitize itself can reject the handoff.
        with patch.object(collector, 'sanitize_fetch', side_effect=reject):
            _, diagnostic, root = self.cli()
        self.assertEqual(diagnostic['stage'], 'notion_sanitize')
        self.assertEqual(diagnostic['notionErrors'], [{'code': 'notion_server_error', 'table': 'companies',
            'http_status': 503, 'notion_code': 'service_unavailable'}])
        self.assertFalse((root / 'work/notion-fetch.json').exists())

    def test_real_notion_http_failures_keep_code_stage_table_status_and_retry_counts(self):
        for status, code in ((401,'notion_unauthorized'), (403,'notion_forbidden'),
                             (404,'notion_not_found'), (429,'notion_rate_limited'), (503,'notion_server_error')):
            with self.subTest(status=status):
                result, diagnostic, root = self.cli(str(status), mutations=[{'op':'http',
                    'match':{'table':'industries','kind':'schema'}, 'responses':[{'status':status,
                    'headers':{'X-Debug':SECRET}, 'body':{'code':'unauthorized','message':SECRET}}]}])
                self.assertEqual(result,2)
                self.assertEqual(diagnostic['code'],'no_last_good')
                self.assertIn(code,diagnostic['blockers'])
                self.assertEqual(diagnostic['stage'],'notion_normalize')
                self.assertEqual(diagnostic['table'],'industries')
                note=next(n for n in diagnostic['notionErrors'] if n['table']=='industries')
                self.assertEqual(note['code'],code)
                self.assertEqual(note['http_status'],status)
                self.assertEqual(diagnostic['counts']['notionRetries'],3 if status in (429,503) else 0)
                self.export(root/'work',root/'artifact')

    def test_real_market_gate_keeps_detailed_current_diagnostic(self):
        def market(*args, **kwargs):
            result = fixture_market(*args, **kwargs)
            data = kwargs['snapshot_sink']['data']
            data['meta']['blockers'] = [BLOCKER, 'index_observation_missing_or_stale']
            data['meta']['issues'] = [{'kind': 'daily', 'status': 'stale', 'symbol': 'NVDA',
                'sourceDate': '2026-10-20', 'body': SECRET}]
            return result
        status, diagnostic, _ = self.cli(market=market)
        self.assertEqual(status, 2)
        self.assertEqual(diagnostic['stage'], 'release_gates')
        self.assertIn(BLOCKER, diagnostic['blockers'])
        self.assertIn('index_observation_missing_or_stale', diagnostic['blockers'])
        self.assertEqual(diagnostic['marketIssues'][0]['symbol'], 'NVDA')

    def test_blocked_market_never_appends_normal_notion_summary_to_github(self):
        self.env['GITHUB_STEP_SUMMARY']=str(self.root/'github-summary.md')
        plain='ordinary_notion_focus_for_failure_summary_sentinel'
        self.assertIsNone(collector.bundle.SECRET_VALUE.search(plain))
        original_apply=collector.build.apply_research
        def apply(*args,**kwargs):
            data=original_apply(*args,**kwargs)
            data['meta']['weekly']['focus']=plain
            return data
        def market(*args, **kwargs):
            result=fixture_market(*args, **kwargs)
            kwargs['snapshot_sink']['data']['meta']['blockers']=[BLOCKER]
            return result
        with patch.object(collector.build,'apply_research',side_effect=apply), \
             patch.object(collector, 'step_summary', wraps=collector.step_summary) as summary:
            status,_,root=self.cli(market=market)
        self.assertEqual(status,2)
        self.assertTrue(all(not call.args and 'error' in call.kwargs for call in summary.call_args_list))
        text=(self.root/'github-summary.md').read_text('utf-8')
        self.assertIn('本次更新未完成',text)
        self.assertNotIn('本周主线：',text)
        self.assertNotIn(plain,text+self.stdout)
        out=root/'artifact';self.export(root/'work',out)
        self.assertTrue(all(plain not in p.read_text('utf-8') for p in out.iterdir()))
        self.env['GITHUB_STEP_SUMMARY']=str(self.root/'bundle-failure-summary.md')
        with patch.object(collector.build,'apply_research',side_effect=apply), \
             patch.object(collector.bundle,'write_bundle',side_effect=RuntimeError(plain)):
            status,diagnostic,root=self.cli('bundle-failure')
        self.assertEqual(status,1)
        self.assertEqual(diagnostic['stage'],'bundle_write')
        self.assertNotIn(plain,self.stdout+(self.root/'bundle-failure-summary.md').read_text('utf-8'))
        out=root/'artifact';self.export(root/'work',out)
        self.assertTrue(all(plain not in p.read_text('utf-8') for p in out.iterdir()))
        fixtures=FixtureSet(self.root/'success-fixtures');transport=FakeTransport(fixtures)
        with patch.object(collector.build,'apply_research',side_effect=apply):
            result=collector.collect(out=self.root/'success/receipt.json',work=self.root/'success-work',
                token=SECRET,transport=transport,market_collect=fixture_market,clock=lambda:CLOCK,env=self.env,
                live_dry_run=True,sleep=transport.sleep,pace=transport.pace)
        self.assertIn(plain,result['summary'])
        self.assertIn(plain,(self.root/'success-work/step-summary.md').read_text('utf-8'))

    def test_diagnostic_write_failure_stays_failed_and_no_bundle(self):
        original = collector.save_json
        def save(path, value):
            if Path(path).name == 'diagnostic.json':
                raise OSError(SECRET)
            return original(path, value)
        def market(*args, **kwargs):
            raise ResearchAbort(BLOCKER)
        with patch.object(collector, 'save_json', side_effect=save):
            # cli helper reads the diagnostic, so exercise main directly here.
            output = io.StringIO()
            with patch.object(collector.os, 'environ', {}), patch.object(collector, 'collect', side_effect=ResearchAbort(BLOCKER)), contextlib.redirect_stdout(output):
                status = collector.main(['--out', str(self.root/'out/receipt.json'), '--work', str(self.root/'work')])
        self.assertEqual(status, 2)
        self.assertFalse((self.root/'out').exists())
        self.assertIs(json.loads(output.getvalue())['publicationAuthorized'], False)
        self.assertNotIn(SECRET, output.getvalue())

    def export(self, work, out):
        process = subprocess.run([sys.executable, '-B', str(ROOT/'radar/scripts/collection_diagnostic.py'),
            '--work', str(work), '--out', str(out)], capture_output=True, text=True, timeout=20,
            env={k:v for k,v in os.environ.items() if k != 'NOTION_TOKEN'})
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertNotIn(SECRET, process.stdout + process.stderr)
        return json.loads((out/'diagnostic.json').read_text('utf-8'))

    def test_production_export_cli_resanitizes_allowlist_and_has_small_file_limit(self):
        work = self.root/'work'; work.mkdir()
        value = {'code': BLOCKER, 'stage': 'market_collect', 'table': SECRET,
            'blockers': [BLOCKER, SECRET] * 100, 'raw': SECRET,
            'counts': {'notionRequests': 13, 'notionRetries': True, SECRET: SECRET},
            'marketIssues': [{'kind': 'daily', 'status': 'stale', 'symbol': 'LEAKSECRET123',
                'sourceDate': '2026-10-21', 'raw': SECRET}] * 110,
            'notionErrors': [{'table': 'companies', 'code': 'notion_timeout', 'http_status': 503, 'body': SECRET}] * 25}
        (work/'diagnostic.json').write_text(json.dumps(value), encoding='utf-8')
        (work/'notion-fetch.json').write_text(SECRET, encoding='utf-8')
        (work/'step-summary.md').write_text(SECRET, encoding='utf-8')
        out = self.root/'artifact'; diagnostic = self.export(work, out)
        self.assertEqual(set(p.name for p in out.iterdir()), {'diagnostic.json', 'step-summary.md'})
        self.assertLess(sum(p.stat().st_size for p in out.iterdir()), 32768)
        self.assertEqual(diagnostic['blockers'], [BLOCKER])
        self.assertEqual(diagnostic['counts'], {'notionRequests': 13})
        self.assertEqual(len(diagnostic['marketIssues']), 100)
        self.assertEqual(len(diagnostic['notionErrors']), 20)
        for path in out.iterdir():
            self.assertNotIn(SECRET, path.read_text('utf-8'))
            self.assertNotIn('LEAKSECRET123', path.read_text('utf-8'))

    def test_invalid_oversized_or_malformed_diagnostics_export_only_safe_fallback(self):
        for index, content in enumerate(('{', '[]', json.dumps({'code': []}), 'x' * 70000)):
            work = self.root/str(index); work.mkdir()
            (work/'diagnostic.json').write_text(content, encoding='utf-8')
            diagnostic = self.export(work, self.root/f'artifact-{index}')
            self.assertEqual(diagnostic['code'], 'collection_failed')
            self.assertEqual(diagnostic['notionErrors'], [])

    def test_export_rejects_symbolic_link_input_without_reading_target(self):
        # Mock the lstat boundary so this test also covers Windows without link privileges.
        work=self.root/'work'; work.mkdir()
        (work/'diagnostic.json').write_text(json.dumps({'code':BLOCKER}), encoding='utf-8')
        with patch.object(Path, 'is_symlink', return_value=True), \
             patch.object(Path, 'open', side_effect=AssertionError('must not follow links')):
            value = collector.read_diagnostic(work/'diagnostic.json')
        self.assertEqual(value, {'code':'collection_failed','notionErrors':[]})

    def test_nonregular_diagnostic_input_is_rejected_before_open(self):
        path=self.root/'diagnostic.json'; path.mkdir()
        with patch.object(collector.os, 'open', side_effect=AssertionError('must not open special files')):
            self.assertEqual(collector.read_diagnostic(path), {'code':'collection_failed','notionErrors':[]})
        if hasattr(os,'mkfifo'):
            fifo=self.root/'fifo.json'; os.mkfifo(fifo)
            with patch.object(collector.os, 'open', side_effect=AssertionError('must not wait on FIFO')):
                self.assertEqual(collector.read_diagnostic(fifo), {'code':'collection_failed','notionErrors':[]})

    def test_failed_summary_rewrite_cannot_enter_safe_export(self):
        work=self.root/'work'; work.mkdir()
        (work/'step-summary.md').write_text(SECRET, encoding='utf-8')
        output=io.StringIO()
        with patch.object(collector.os, 'environ', {}), \
             patch.object(collector, 'collect', side_effect=ResearchAbort(BLOCKER)), \
             patch.object(collector, 'write_summary', side_effect=OSError(SECRET)), \
             contextlib.redirect_stdout(output):
            status=collector.main(['--out',str(self.root/'out/receipt.json'),'--work',str(work)])
        self.assertEqual(status,2)
        self.assertNotIn(SECRET,output.getvalue())
        out=self.root/'artifact'; self.export(work,out)
        self.assertNotIn(SECRET,(out/'step-summary.md').read_text('utf-8'))

    def test_live_diagnostic_exit_resanitizes_untrusted_saved_json(self):
        work=self.root/'work'; work.mkdir()
        (work/'diagnostic.json').write_text(json.dumps({'code':'no_last_good','raw':SECRET,
            'notionErrors':[{'code':'notion_unauthorized','table':'companies','body':SECRET}]}), encoding='utf-8')
        result = live.verify(source=self.root/'missing', destination=self.root/'release', artifact=self.root/'artifact',
            work=work, env=self.env)
        self.assertEqual(result['code'], 'notion_unauthorized')
        self.assertFalse(result['ready']); self.assertFalse(result['verified'])
        self.assertIs(result['publicationAuthorized'], False)
        for path in (self.root/'artifact').iterdir():
            self.assertNotIn(SECRET, path.read_text('utf-8'))

    def test_workflow_exports_safe_diagnostics_after_failed_collect_and_never_uploads_handoff(self):
        workflow = json.loads((ROOT/'.github/workflows/radar-production.yml').read_text('utf-8'))
        steps = workflow['jobs']['refresh']['steps']
        export = next(s for s in steps if 'collection_diagnostic.py' in s.get('run', ''))
        self.assertIn('always()', export['if'])
        self.assertIn("steps.collect.outcome == 'failure'", export['if'])
        self.assertNotIn('env', export)
        upload = next(s for s in steps if s.get('uses','').startswith('actions/upload-artifact@'))
        paths = upload['with']['path'].splitlines()
        self.assertIn('${{ runner.temp }}/radar-diagnostics/diagnostic.json', paths)
        self.assertIn('${{ runner.temp }}/radar-diagnostics/step-summary.md', paths)
        self.assertLess(steps.index(export), steps.index(upload))
        self.assertNotIn('notion-fetch', upload['with']['path'])
        summary = next(p for p in paths if 'radar-work/step-summary.md' in p)
        self.assertIn("steps.collect.outcome == 'success'", summary)
        self.assertIn("|| ''", summary)
        self.assertFalse(any('*' in p for p in paths))
        self.assertEqual(upload['if'], 'always()')

    def taiwan_daily_packet(self, timestamp):
        # Boundaries and the negative timestamp reproduce the separately saved
        # 2026-10-27 public probe. Prices and the positive packet are synthetic;
        # neither packet is represented as the earlier live response.
        payload={'chart':{'result':[{'meta':{'symbol':'2383.TW','currency':'TWD',
            'exchangeTimezoneName':'Asia/Taipei','gmtoffset':28800,'regularMarketTime':timestamp,
            'currentTradingPeriod':{'regular':{'start':1793062800,'end':1793079000}}},
            'timestamp':[timestamp], 'indicators':{'quote':[{'close':[100.0],'high':[101.0]}],
                'adjclose':[{'adjclose':[100.0]}]}}]}}
        received='2026-10-27T10:53:35.803832+00:00'
        class Packet:
            def yahoo(self, path):
                return payload
        before=json.dumps(payload,sort_keys=True)
        with patch.object(collector.build.quotes,'stamp',side_effect=lambda **values:
                {**values,'schemaVersion':2,'receivedAt':received}):
            record=collector.build.quotes.yahoo_daily(Packet(),'2383.TW')
        self.assertEqual(json.dumps(payload,sort_keys=True),before)
        return payload,record

    def test_taiwan_same_day_after_close_timestamp_outside_session_stays_unconfirmed(self):
        payload,record=self.taiwan_daily_packet(1793079015)
        before=json.dumps(record,sort_keys=True)
        now=dt.datetime.fromisoformat('2026-10-27T18:54:00+08:00')
        company={'sym':'2383.TW','mkt':'台股','cur':'TWD'}
        self.assertEqual(record['asOf'],'2026-10-27')
        self.assertEqual(record['barTimestamps']['2026-10-27'],1793079015)
        self.assertEqual(payload['chart']['result'][0]['meta']['regularMarketTime'],1793079015)
        self.assertEqual(record['finality'],{'method':'provider-session-boundary',
            'start':1793062800,'end':1793079000})
        self.assertEqual(record['barTimestamps']['2026-10-27']-record['finality']['end'],15)
        self.assertGreater(now.timestamp(),record['finality']['end'])
        self.assertEqual(record['phase'],'unknown')
        self.assertFalse(collector.build.latest.equity_bar_final('2026-10-27',1793079015,
            record['timezone'],record['finality'],record['receivedAt']))
        for policy in (False,True):
            with self.subTest(calendar_policy=policy):
                selected,snapshot=collector.build.latest.select_daily([company],{'2383.TW':record},now,
                    calendar_policy=policy)
                self.assertEqual(selected,{})
                self.assertIsNone(snapshot['selectedDate'])
                self.assertEqual(snapshot['status'],'incomplete')
                self.assertEqual(snapshot['sourceAsOfByMarket'],{'台股':['2026-10-27']})
                self.assertEqual(json.dumps(record,sort_keys=True),before)

    def test_taiwan_same_day_session_bar_with_after_close_receipt_keeps_original_proof(self):
        # Independent positive packet, not a repaired version of the rejected
        # 13:30:15 observation. The bar is stamped at the real session start.
        _,record=self.taiwan_daily_packet(1793062800)
        before=json.dumps(record,sort_keys=True)
        now=dt.datetime.fromisoformat('2026-10-27T18:54:00+08:00')
        company={'sym':'2383.TW','mkt':'台股','cur':'TWD'}
        self.assertEqual(record['asOf'],'2026-10-27')
        self.assertEqual(record['phase'],'closed')
        self.assertLess(record['barTimestamps']['2026-10-27'],record['finality']['end'])
        self.assertGreater(dt.datetime.fromisoformat(record['receivedAt']).timestamp(),record['finality']['end'])
        self.assertTrue(collector.build.latest.equity_bar_final('2026-10-27',1793062800,
            record['timezone'],record['finality'],record['receivedAt']))
        for policy in (False,True):
            with self.subTest(calendar_policy=policy):
                selected,snapshot=collector.build.latest.select_daily([company],{'2383.TW':record},now,
                    calendar_policy=policy)
                self.assertEqual(snapshot['selectedDate'],'2026-10-27')
                self.assertEqual(snapshot['status'],'complete')
                for key in ('bars','barTimestamps','finality','receivedAt','timezone'):
                    self.assertEqual(selected['2383.TW'][key],record[key])
                self.assertEqual(json.dumps(record,sort_keys=True),before)


if __name__ == '__main__':
    unittest.main()
