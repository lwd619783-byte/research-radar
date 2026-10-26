"""Offline collection, replay, dry-run boundaries and exact synthetic-secret scans."""
import contextlib
import copy
import datetime as dt
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import acceptance_bundle as bundle
import live_notion_dry_run as live
import notion_normalize
import production_collect as collector
import production_release as release
from notion_fixtures import FixtureSet, FakeTransport
from notion_fixture_market import fixture_market
from research_snapshot import ResearchAbort

SENTINEL = 'ntn_EXACT_OFFLINE_SECRET_SENTINEL_NEVER_REAL'
CLOCK = dt.datetime.fromisoformat('2026-10-21T18:15:00+08:00')


class ProductionCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixtures = FixtureSet(self.root / 'fixtures')
        self.transport = FakeTransport(self.fixtures)
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
                    'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH,
                    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
                    'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a' * 40}
        self.network = patch('socket.socket', side_effect=AssertionError('Tests must never open a network socket'))
        self.network.start(); self.addCleanup(self.network.stop)

    def collect(self, name='current', **kwargs):
        return collector.collect(out=self.root / name / 'receipt.json', work=self.root / (name + '-work'),
            token=SENTINEL, transport=self.transport, market_collect=kwargs.pop('market_collect', fixture_market),
            clock=lambda: CLOCK, env=self.env, live_dry_run=True,
            sleep=self.transport.sleep, pace=self.transport.pace, **kwargs)

    def no_leak(self):
        for path in self.root.rglob('*'):
            # Input fixtures may deliberately contain the sentinel for a source
            # redaction test; only generated files are output/artifact evidence.
            if path.is_file() and 'fixtures' not in path.relative_to(self.root).parts:
                self.assertNotIn(SENTINEL.encode(), path.read_bytes(), str(path))

    def test_sanitized_replay_matches_raw_normalization_and_exclusion(self):
        config = collector.build.research_config(); contract = collector.build.load_notion_contract(config)
        self.fixtures.mutate([{'op': 'page_attr', 'table': 'industries', 'row': '消费', 'attr': 'in_trash', 'value': True}])
        raw = collector.fetch_all(contract, config['notion'], token=SENTINEL, transport=self.transport,
             sleep=self.transport.sleep, pace=self.transport.pace, fixed_clock=CLOCK)
        for table in raw['tables'].values():
            for page in table['pages']:
                page['created_by'] = {'id': 'user-private', 'email': 'private@example.test'}
                page['last_edited_by'] = {'id': 'private-editor'}
        clean = collector.sanitize_fetch(raw, contract, fetched_at=CLOCK.isoformat(), token=SENTINEL)
        a = notion_normalize.normalize(raw, contract, CLOCK, config=config)
        b = notion_normalize.normalize(clean, contract, CLOCK, config=config)
        self.assertEqual(a, b)
        text = json.dumps(clean)
        for forbidden in ('created_by', 'last_edited_by', 'private@example.test', 'private-editor', SENTINEL):
            self.assertNotIn(forbidden, text)
        self.assertEqual(clean['requests'], {'total': 13, 'GET': 6, 'POST': 7, 'retries': 0})
        self.assertGreater(b['notion']['counts']['industries']['excluded'], 0)

    def test_same_run_binding_rehearsal_and_actual_node_verifier(self):
        result = self.collect()
        source = self.root / 'current'
        bundle.verify_bundle(source)
        self.assertEqual(result['receipt']['purpose'], 'offline-rehearsal')
        self.assertTrue(result['data']['meta']['reviewPreview'])
        self.assertEqual(result['data']['meta']['notion']['requests']['total'], 13)
        self.assertEqual(result['receipt']['publication']['dataSHA256'], bundle.data_digest(result['data']))
        with self.assertRaises(ValueError):
            release.prepare_dry_run(source, self.root / 'real-dry-run', now=CLOCK, env=self.env)
        production_env = {**self.env, 'GITHUB_REF': 'refs/heads/' + collector.SOURCE_BRANCH}
        with self.assertRaises(ValueError):
            release.prepare(source, self.root / 'production', now=CLOCK, env=production_env)
        manifest = release.prepare_rehearsal(source, self.root / 'rehearsal', now=CLOCK, env=self.env)
        self.assertEqual(manifest['purpose'], 'offline-rehearsal')
        self.assertIs(manifest['publicationAuthorized'], False)
        node = shutil.which('node')
        self.assertIsNotNone(node)
        child = {'PATH': os.environ.get('PATH', ''), 'SYSTEMROOT': os.environ.get('SYSTEMROOT', '')}
        process = subprocess.run([node, 'verify-release.cjs', '--check-only'], cwd=self.root / 'rehearsal',
                                 env=child, capture_output=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8', 'replace'))
        rejected = subprocess.run([node, 'verify-release.cjs'], cwd=self.root / 'rehearsal',
                                  env={**child, 'VERCEL_ENV': 'production', 'VERCEL_GIT_COMMIT_REF': 'production',
                                       'VERCEL_GIT_COMMIT_SHA': 'b' * 40}, capture_output=True, timeout=60)
        self.assertNotEqual(rejected.returncode, 0)
        self.no_leak()

    def test_no_financial_rows_do_not_crash_collection(self):
        for document in self.fixtures.query_documents('financials'):
            document['results'].clear()
        result = self.collect()
        self.assertEqual(result['receipt']['publication']['financialVerified'], 0)
        self.assertEqual(result['receipt']['publication']['financialPartial'], 0)
        self.assertTrue(all(company.get('provenance', {}).get('financial') is None
                            for company in result['data']['companies']))
        self.no_leak()

    def test_market_blocker_writes_only_work_diagnostics(self):
        def failed_market(*args, **kwargs):
            answer = fixture_market(*args, **kwargs)
            for company in kwargs['snapshot_sink']['data']['companies']:
                company['price'] = None
            return answer
        with self.assertRaises(ResearchAbort) as raised:
            self.collect(market_collect=failed_market)
        self.assertIn('quotes_coverage_low', raised.exception.codes)
        self.assertFalse((self.root / 'current').exists())
        self.assertTrue((self.root / 'current-work/diagnostic.json').is_file())
        self.no_leak()

    def test_cli_removes_secret_before_downstream_and_sanitizes_exception(self):
        env = {**self.env, 'NOTION_TOKEN': SENTINEL}
        def reject(**kwargs):
            self.assertEqual(kwargs['token'], SENTINEL)
            self.assertNotIn('NOTION_TOKEN', collector.os.environ)
            raise RuntimeError(SENTINEL)
        output = io.StringIO()
        with patch.object(collector.os, 'environ', env), patch.object(collector, 'collect', side_effect=reject), \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = collector.main(['--out', str(self.root / 'out/receipt.json'), '--work', str(self.root / 'work'), '--live-dry-run'])
        self.assertEqual(code, 1)
        self.assertNotIn(SENTINEL, output.getvalue())
        self.assertNotIn('NOTION_TOKEN', env)
        self.no_leak()

    def test_missing_last_good_auth_failure_has_safe_diagnostic_artifact(self):
        for status, expected in ((401, 'notion_unauthorized'), (403, 'notion_forbidden'), (404, 'notion_not_found')):
            work = self.root / str(status)
            diagnostics = {'code': 'no_last_good', 'notionErrors': [
                {'code': expected, 'table': 'industries', 'http_status': status}]}
            collector.save_json(work / 'diagnostic.json', diagnostics)
            result = live.verify(source=self.root / 'absent-bundle', destination=self.root / 'absent-release',
                artifact=self.root / f'artifact-{status}', work=work, env=self.env)
            self.assertEqual(result['code'], expected)
            if status == 403:
                self.assertIn('第 2 步', result['action'])
            self.assertFalse(result['ready']); self.assertFalse(result['verified'])
            self.assertIs(result['publicationAuthorized'], False)
            self.assertEqual(set(result['files']), {'result.json', 'diagnostic.json', 'step-summary.md'})
        self.no_leak()

    def test_live_helper_cannot_receive_secret_or_wrong_execution(self):
        for env in ({**self.env, 'NOTION_TOKEN': SENTINEL},
                    {**self.env, 'GITHUB_REF': 'refs/heads/' + collector.SOURCE_BRANCH},
                    {**self.env, 'GITHUB_EVENT_NAME': 'pull_request'},
                    {**self.env, 'GITHUB_RUN_ATTEMPT': '2'}):
            with self.subTest(keys=list(env)), self.assertRaises(ValueError):
                live.verify(source=self.root / 'none', destination=self.root / 'release',
                            artifact=self.root / 'artifact', env=env)
        self.assertFalse((self.root / 'artifact').exists())

    def test_missing_token_global_error_survives_sanitized_handoff(self):
        config = collector.build.research_config(); contract = collector.build.load_notion_contract(config)
        raw = collector.fetch_all(contract, config['notion'], token='', transport=self.transport,
             sleep=self.transport.sleep, pace=self.transport.pace, fixed_clock=CLOCK)
        for table in raw['tables'].values():
            table.pop('error', None)
        clean = collector.sanitize_fetch(raw, contract, fetched_at=CLOCK.isoformat())
        self.assertEqual(clean['requests']['total'], 0)
        self.assertEqual(self.transport.requests, 0)
        self.assertTrue(all(row['code'] == 'notion_token_missing' for row in clean['tables'].values()))
        self.assertEqual(live.classify(diagnostics={'code': 'notion_token_missing'})['code'], 'notion_token_missing')

    def test_echoed_http_secret_never_reaches_log_work_or_artifact(self):
        self.fixtures.mutate([{'op': 'http', 'match': {'table': 'industries', 'kind': 'schema'},
            'responses': [{'status': 401, 'headers': {'X-Debug': SENTINEL},
                           'body': {'code': 'unauthorized', 'message': SENTINEL}}]}])
        original = collector.collect
        def offline(**kwargs):
            return original(**kwargs, transport=self.transport, market_collect=fixture_market,
                clock=lambda: CLOCK, sleep=self.transport.sleep, pace=self.transport.pace)
        output = io.StringIO()
        with patch.object(collector.os, 'environ', {**self.env, 'NOTION_TOKEN': SENTINEL}), \
             patch.object(collector, 'collect', side_effect=offline), contextlib.redirect_stdout(output), \
             contextlib.redirect_stderr(output):
            code = collector.main(['--out', str(self.root / 'current/receipt.json'),
                '--work', str(self.root / 'work'), '--live-dry-run'])
        self.assertEqual(code, 2)
        self.assertFalse((self.root / 'current').exists())
        result = live.verify(source=self.root / 'current', destination=self.root / 'release',
            artifact=self.root / 'artifact', work=self.root / 'work', env=self.env)
        self.assertEqual(result['code'], 'notion_unauthorized')
        self.assertNotIn(SENTINEL, output.getvalue())
        self.no_leak()

    def test_first_complete_refresh_is_content_gate_not_code_failure(self):
        data = {'meta': {'notion': {'fallbackTables': []}, 'weekly': {'mode': 'auto'}}}
        self.assertEqual(live.classify(data)['code'], 'weekly_refresh_required')
        data['meta']['weekly']['mode'] = 'ai'
        self.assertTrue(live.classify(data)['ready'])
        data['meta']['notion']['fallbackTables'] = [{'code': 'notion_timeout', 'table': 'daily'}]
        self.assertEqual(live.classify(data)['code'], 'live_notion_fallback')

    def test_v2_baseline_has_no_last_good_without_reading_snapshot(self):
        baseline = self.root / 'baseline'; baseline.mkdir()
        (baseline / 'release.json').write_text('{"schemaVersion":2}', encoding='utf-8')
        contract = collector.build.load_notion_contract(collector.build.research_config())
        with patch.object(collector, 'load_last_good', side_effect=AssertionError('Do not read a v2 research snapshot')):
            self.assertIsNone(collector.baseline_snapshot(baseline, contract))


if __name__ == '__main__':
    unittest.main()
