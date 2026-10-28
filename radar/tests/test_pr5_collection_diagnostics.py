"""Safe controlled-failure diagnostics; all transports and secrets are synthetic."""
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import production_collect as collector
import live_notion_dry_run as live
from notion_fixtures import FixtureSet, FakeTransport
from notion_fixture_market import fixture_market
from research_snapshot import ResearchAbort

SENTINEL = 'ntn_OFFLINE_DIAGNOSTIC_SENTINEL_NEVER_REAL'
CLOCK = dt.datetime.fromisoformat('2026-10-21T18:15:00+08:00')
BLOCKER = 'stale_quotes_not_safe_in_all_frozen_views'


class CollectionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
                    'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH,
                    'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
                    'GITHUB_RUN_ID': '123', 'GITHUB_SHA': 'a' * 40}
        guard = patch('socket.socket.connect', side_effect=AssertionError('no live network'))
        guard.start(); self.addCleanup(guard.stop)

    def blocked_market(self, *args, **kwargs):
        result = fixture_market(*args, **kwargs)
        data = kwargs['snapshot_sink']['data']
        data['meta']['blockers'] = [BLOCKER, 'index_observation_missing_or_stale']
        data['meta']['issues'] = [
            {'kind': 'daily', 'symbol': '3110.T', 'status': 'no_common_completed_observation'},
            {'kind': 'index', 'symbol': '^IXIC', 'status': 'missing_or_unconfirmed_snapshot',
             'sourceDate': '2026-10-19', 'requiredDate': '2026-10-20'}]
        next(c for c in data['companies'] if c['sym'] == '3110.T')['marketCalendar'] = {
            'quoteDate': '2026-10-20', 'expectedCompletedDate': '2026-10-21'}
        data['meta']['marketCalendar'] = {'exchanges': {'XNAS': {'expectedCompletedDate': '2026-10-20'}}}
        return result

    def invoke_real_cli(self):
        fixtures = FixtureSet(self.root/'fixtures'); transport = FakeTransport(fixtures)
        original = collector.collect
        def injected(**kwargs):
            self.assertEqual(kwargs['token'], SENTINEL)
            self.assertNotIn('NOTION_TOKEN', collector.os.environ)
            return original(**kwargs, transport=transport, market_collect=self.blocked_market,
                            clock=lambda: CLOCK, sleep=transport.sleep, pace=transport.pace)
        output = io.StringIO()
        with patch.object(collector.os, 'environ', {**self.env, 'NOTION_TOKEN': SENTINEL}), \
             patch.object(collector, 'collect', side_effect=injected), contextlib.redirect_stdout(output):
            exit_code = collector.main(['--out', str(self.root/'out/receipt.json'),
                '--work', str(self.root/'work'), '--live-dry-run'])
        return exit_code, output.getvalue()

    def test_real_cli_preserves_controlled_market_blockers_and_exact_issue_dates(self):
        exit_code, text = self.invoke_real_cli()
        self.assertEqual(exit_code, 2)
        diagnostic = json.loads((self.root/'work/diagnostic.json').read_text('utf-8'))
        self.assertEqual(diagnostic['code'], 'index_observation_missing_or_stale')
        self.assertEqual(diagnostic['blockers'], ['index_observation_missing_or_stale', BLOCKER])
        daily = next(i for i in diagnostic['marketIssues'] if i['kind'] == 'daily')
        self.assertEqual(daily, {'kind': 'daily', 'status': 'no_common_completed_observation',
            'symbol': '3110.T', 'sourceDate': '2026-10-20', 'expectedCompletedDate': '2026-10-21'})
        index = next(i for i in diagnostic['marketIssues'] if i['kind'] == 'index')
        self.assertEqual(index['symbol'], '^IXIC')
        self.assertEqual(index['sourceDate'], '2026-10-19')
        self.assertEqual(index['expectedCompletedDate'], '2026-10-20')
        self.assertNotIn('collection_failed', text)
        self.assertFalse((self.root/'out').exists())
        self.assertNotIn(SENTINEL, text)

    def test_missing_bundle_stays_unpublishable_and_exports_same_safe_files(self):
        self.invoke_real_cli()
        result = live.verify(source=self.root/'out', destination=self.root/'release',
            artifact=self.root/'artifact', work=self.root/'work', env=self.env)
        self.assertFalse(result['ready']); self.assertFalse(result['verified'])
        self.assertIs(result['publicationAuthorized'], False)
        self.assertEqual(set(result['files']), {'result.json', 'diagnostic.json', 'step-summary.md'})
        artifact = json.loads((self.root/'artifact/diagnostic.json').read_text('utf-8'))
        self.assertIn(BLOCKER, artifact['blockers'])
        self.assertEqual(len(artifact['marketIssues']), 2)
        self.assertFalse((self.root/'release').exists())

    def test_unknown_codes_token_shaped_values_paths_and_raw_fields_are_filtered(self):
        issue = {'kind': 'daily', 'status': 'stale', 'symbol': '3110.T',
                 'sourceDate': '2026-10-20', 'expectedCompletedDate': '2026-10-21',
                 'response': SENTINEL, 'path': r'C:\private\secret.txt'}
        hostile = [issue, {**issue, 'symbol': SENTINEL, 'sourceDate': SENTINEL},
                   {**issue, 'kind': SENTINEL}, {**issue, 'status': SENTINEL},
                   {**issue, 'symbol': '../private/path', 'sourceDate': '2026-13-99'}]
        result = collector.safe_collection_diagnostic(SENTINEL,
            blockers=[BLOCKER, SENTINEL, 'unknown_blocker', {'raw': SENTINEL}], market_issues=hostile,
            notion_errors=[{'code': 'notion_unauthorized', 'table': 'companies',
                            'http_status': 401, 'detail': {'raw': SENTINEL}}, {'code': SENTINEL}])
        encoded = json.dumps(result)
        self.assertEqual(result['code'], 'collection_failed')
        self.assertEqual(result['blockers'], [BLOCKER])
        for forbidden in (SENTINEL, 'unknown_blocker', 'private', 'response', 'detail', '2026-13-99'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(result['notionErrors'][0], {'code': 'notion_unauthorized', 'table': 'companies', 'http_status': 401})
        collector.bundle.check_sensitive(result)

    def test_cli_resanitizes_saved_diagnostic_instead_of_copying_arbitrary_fields(self):
        work = self.root/'work'; work.mkdir()
        def reject(**kwargs):
            (work/'diagnostic.json').write_text(json.dumps({'code': BLOCKER,
                'blockers': [BLOCKER, SENTINEL], 'raw': SENTINEL,
                'marketIssues': [{'kind': 'daily', 'status': 'stale', 'symbol': SENTINEL,
                                  'expectedCompletedDate': '2026-10-21', 'response': SENTINEL}]}), encoding='utf-8')
            raise ResearchAbort(BLOCKER, codes=[BLOCKER, SENTINEL])
        output = io.StringIO()
        with patch.object(collector.os, 'environ', {}), patch.object(collector, 'collect', side_effect=reject), contextlib.redirect_stdout(output):
            code = collector.main(['--out', str(self.root/'out/receipt.json'), '--work', str(work)])
        self.assertEqual(code, 2)
        saved = (work/'diagnostic.json').read_text('utf-8')
        self.assertNotIn(SENTINEL, saved + output.getvalue())
        self.assertEqual(json.loads(saved)['blockers'], [BLOCKER])
        self.assertNotIn('raw', json.loads(saved))

    def test_cli_unknown_failure_does_not_inherit_stale_diagnostic(self):
        work = self.root/'work'; work.mkdir()
        collector.save_json(work/'diagnostic.json', {'code': BLOCKER, 'blockers': [BLOCKER]})
        output = io.StringIO()
        with patch.object(collector.os, 'environ', {}), \
             patch.object(collector, 'collect', side_effect=ResearchAbort(SENTINEL)), contextlib.redirect_stdout(output):
            code = collector.main(['--out', str(self.root/'out/receipt.json'), '--work', str(work)])
        self.assertEqual(code, 2)
        saved = json.loads((work/'diagnostic.json').read_text('utf-8'))
        self.assertEqual(saved, {'code': 'collection_failed', 'notionErrors': []})
        self.assertNotIn(SENTINEL, output.getvalue())

    def test_issue_dates_validate_and_output_is_bounded(self):
        rows = [{'kind': 'index', 'status': 'missing_or_unconfirmed_snapshot', 'symbol': '^HSI',
                 'sourceDate': '2026-02-30', 'expectedCompletedDate': '2026-10-21'}] * 110
        accepted = collector.safe_market_issues(rows)
        self.assertEqual(len(accepted), 100)
        self.assertTrue(all('sourceDate' not in row for row in accepted))
        self.assertEqual(collector.safe_market_issues({'response': SENTINEL}), [])

    def test_malformed_handoff_and_non_string_error_codes_cannot_preserve_unsafe_diagnostic(self):
        payloads = [[], 'invalid root', {'tables': []}, {'tables': 'invalid tables'},
                    {'tables': {'companies': []}}, {'tables': {'companies': {'error': []}}},
                    {'tables': {'companies': {'error': {'code': {}, 'detail': SENTINEL}}}},
                    {'tables': {'companies': {'error': {'code': [], 'detail': SENTINEL}}}},
                    {'tables': {'companies': {'error': {'code': SENTINEL, 'raw': SENTINEL}}}}]
        for i, payload in enumerate(payloads):
            with self.subTest(case=i):
                work = self.root/str(i); work.mkdir()
                (work/'notion-fetch.json').write_text(json.dumps(payload), encoding='utf-8')
                (work/'diagnostic.json').write_text(json.dumps({'code': BLOCKER,
                    'blockers': [BLOCKER, SENTINEL], 'unknown': SENTINEL}), encoding='utf-8')
                output = io.StringIO()
                with patch.object(collector.os, 'environ', {}), \
                     patch.object(collector, 'collect', side_effect=ResearchAbort(BLOCKER)), contextlib.redirect_stdout(output):
                    code = collector.main(['--out', str(work/'out/receipt.json'), '--work', str(work)])
                self.assertEqual(code, 2)
                saved = json.loads((work/'diagnostic.json').read_text('utf-8'))
                self.assertEqual(saved['blockers'], [BLOCKER])
                self.assertNotIn('unknown', saved)
                self.assertNotIn(SENTINEL, json.dumps(saved)+output.getvalue())
                self.assertTrue(all(n['code']=='notion_bad_json' for n in saved['notionErrors']))
                collector.bundle.check_sensitive(saved)

    def test_invalid_json_handoff_still_writes_minimal_diagnostic(self):
        work = self.root/'invalid-json'; work.mkdir()
        (work/'notion-fetch.json').write_text('{', encoding='utf-8')
        with patch.object(collector.os, 'environ', {}), \
             patch.object(collector, 'collect', side_effect=ResearchAbort(BLOCKER)), contextlib.redirect_stdout(io.StringIO()):
            code = collector.main(['--out', str(work/'out/receipt.json'), '--work', str(work)])
        self.assertEqual(code, 2)
        saved = json.loads((work/'diagnostic.json').read_text('utf-8'))
        self.assertEqual(saved, {'code': BLOCKER, 'blockers': [BLOCKER], 'notionErrors': []})

    def test_summary_failure_cannot_leave_unsafe_previous_diagnostic(self):
        work = self.root/'summary-failed'; work.mkdir()
        (work/'diagnostic.json').write_text(json.dumps({'code': BLOCKER,
            'blockers': [BLOCKER, SENTINEL], 'raw': SENTINEL}), encoding='utf-8')
        output = io.StringIO()
        with patch.object(collector.os, 'environ', {}), \
             patch.object(collector, 'collect', side_effect=ResearchAbort(BLOCKER)), \
             patch.object(collector, 'step_summary', side_effect=RuntimeError(SENTINEL)), \
             contextlib.redirect_stdout(output):
            code = collector.main(['--out', str(work/'out/receipt.json'), '--work', str(work)])
        self.assertEqual(code, 2)
        saved = (work/'diagnostic.json').read_text('utf-8')
        self.assertEqual(json.loads(saved), {'code': BLOCKER, 'blockers': [BLOCKER], 'notionErrors': []})
        self.assertNotIn(SENTINEL, saved+output.getvalue())


if __name__ == '__main__':
    unittest.main()
