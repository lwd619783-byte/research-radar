"""Offline release-chain evidence. Fixture DATA never becomes publishable."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'radar/scripts'))
import acceptance_bundle as bundle
import build
import production_release as release
import release_operations as ops
import research_snapshot
from test_notion_v3 import run_fixture


class V3ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = run_fixture()
        assert result['exit'] == 0, result['logs']
        cls.original = result['DATA']
        cls.snapshot = result['snapshot_object']

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = copy.deepcopy(self.original)
        self.research = copy.deepcopy(self.snapshot)
        self.clock = dt.datetime.fromisoformat(self.research['builtAt'])
        self.env = {'GITHUB_REPOSITORY': release.REPOSITORY,
            'GITHUB_REF': 'refs/heads/v3/pr4-production', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_SHA': 'a'*40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
        self.receipt = {'schemaVersion': 1, 'purpose': 'offline-rehearsal',
            'execution': {key: self.env[key] for key in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')},
            'fixedClock': self.clock.isoformat(), 'publication': {}}
        self.bind()
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('offline release attempted network')).start()
        self.addCleanup(patch.stopall)

    def bind(self):
        self.receipt['publication'] = {'dataSHA256': bundle.data_digest(self.data),
            'asOf': self.data['meta']['asOf'], 'snapshot': self.data['meta']['snapshot'],
            'blockers': build.release_blockers(self.data)}

    def archive(self):
        source = self.root/'archive'
        bundle.write_bundle(source, self.data, self.receipt, self.clock, research_snapshot=self.research)
        return source

    def rehearsal(self):
        source = self.archive()
        destination = self.root/'release'
        manifest = release.prepare_rehearsal(source, destination, now=self.clock, env=self.env)
        return destination, manifest

    def node(self, root, *args):
        return subprocess.run(['node', str(ROOT/'radar/scripts/verify-release.cjs'), *args], cwd=root,
            env=os.environ | {'VERCEL_ENV': 'production', 'VERCEL_GIT_COMMIT_REF': 'production',
                              'VERCEL_GIT_COMMIT_SHA': 'b'*40}, capture_output=True, text=True, encoding='utf-8')

    def test_bundle_binds_canonical_snapshot_and_keeps_fixture_marker(self):
        source = self.archive()
        self.assertEqual({p.name for p in source.iterdir()}, set(bundle.FILES) | {bundle.SNAPSHOT})
        self.assertEqual((source/bundle.SNAPSHOT).read_bytes(), research_snapshot.canonical_json(self.research).encode())
        self.assertTrue(json.loads((source/'DATA.json').read_bytes())['meta']['reviewPreview'])
        manifest = json.loads((source/'manifest.json').read_bytes())
        self.assertEqual(manifest['researchSnapshotSHA256'], self.data['meta']['notion']['snapshotSHA256'])
        bundle.verify_bundle(source)
        self.network.assert_not_called()

    def test_snapshot_missing_tampered_secret_or_extra_shape_never_exposes_archive(self):
        for mutation in ('missing', 'hash', 'clock', 'key', 'token', 'shape'):
            with self.subTest(mutation=mutation):
                snapshot = copy.deepcopy(self.research)
                if mutation == 'missing': snapshot = None
                elif mutation == 'hash': snapshot['tables']['industries']['rows'][0]['props']['名称'] = '测试内容'
                elif mutation == 'clock': snapshot['builtAt'] = '2026-10-20T18:15:00+08:00'
                elif mutation == 'key': snapshot['created_by'] = {'id': 'synthetic-user'}
                elif mutation == 'token': snapshot['tables']['industries']['rows'][0]['props']['名称'] = 'ntn_' + 'SYNTHETIC_ONLY_12345'
                else: snapshot['tables']['industries']['rows'][0]['extra'] = 'not allowed'
                out = self.root/mutation
                with self.assertRaises(bundle.BundleError):
                    bundle.write_bundle(out, self.data, self.receipt, self.clock, research_snapshot=snapshot)
                self.assertFalse(out.exists())

    def test_real_production_and_live_rehearsal_reject_synthetic_archive(self):
        source = self.archive()
        prod_env = self.env | {'GITHUB_REF': 'refs/heads/' + release.SOURCE_BRANCH}
        with self.assertRaisesRegex(ValueError, 'diagnostic_publication_forbidden'):
            release.prepare(source, self.root/'production', self.clock, prod_env)
        with self.assertRaisesRegex(ValueError, 'dry_run_market_gate_failed|real_input'):
            release.prepare_dry_run(source, self.root/'live', self.clock, self.env)
        self.assertFalse((self.root/'production').exists())
        self.assertFalse((self.root/'live').exists())

    def test_diagnostic_guards_are_exact_and_market_errors_still_block(self):
        source = self.archive()
        for key, value in [('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_EVENT_NAME', 'push'),
                           ('GITHUB_REF', 'refs/heads/production'), ('GITHUB_RUN_ATTEMPT', '2')]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'execution_not_allowed'):
                release.prepare_rehearsal(source, self.root/'bad', self.clock, self.env | {key: value})
        with self.assertRaisesRegex(ValueError, 'snapshot_not_fresh'):
            release.prepare_rehearsal(source, self.root/'stale', self.clock + dt.timedelta(minutes=31), self.env)
        self.data['meta']['blockers'].append('missing_required_quote')
        self.bind()
        with self.assertRaisesRegex(ValueError, 'market_gate_failed'):
            release.validate_dry_run(self.data, self.receipt, self.clock, self.env, rehearsal=True)

    def test_full_rehearsal_verifies_but_never_authorizes_publication(self):
        root, manifest = self.rehearsal()
        self.assertEqual(manifest['schemaVersion'], 3)
        self.assertEqual(manifest['purpose'], 'offline-rehearsal')
        self.assertIs(manifest['publicationAuthorized'], False)
        self.assertEqual(manifest['notion'], bundle.notion_summary(self.data))
        self.assertEqual({p.name for p in (root/'public').iterdir()}, {'index.html', 'robots.txt', 'version.json'})
        self.assertEqual((root/bundle.SNAPSHOT).read_bytes(), research_snapshot.canonical_json(self.research).encode())
        _, actual = ops.verify_files(root, allow_dry_run=True)
        self.assertEqual(actual, self.data)
        with self.assertRaisesRegex(ValueError, 'diagnostic_publication_forbidden'):
            ops.verify_files(root)
        checked = self.node(root, '--check-only')
        self.assertEqual(checked.returncode, 0, checked.stderr)
        before = (root/'public/version.json').read_bytes()
        denied = self.node(root)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('diagnostic_publication_forbidden', denied.stderr)
        self.assertEqual((root/'public/version.json').read_bytes(), before)
        with patch.dict(os.environ, self.env | {'GITHUB_REF': 'refs/heads/' + ops.BRANCH}), patch.object(ops, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'diagnostic_publication_forbidden'): ops.publish(root)
            command.assert_not_called()

    def test_snapshot_hash_and_summary_checked_by_python_and_vercel(self):
        root, manifest = self.rehearsal()
        (root/bundle.SNAPSHOT).write_bytes((root/bundle.SNAPSHOT).read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'snapshot_hash_mismatch'): ops.verify_files(root, allow_dry_run=True)
        self.assertIn('snapshot_hash_mismatch', self.node(root, '--check-only').stderr)
        (root/bundle.SNAPSHOT).write_bytes(research_snapshot.canonical_json(self.research).encode())
        manifest['notion']['warningCount'] += 1
        (root/'release.json').write_bytes(bundle.encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'notion_summary_mismatch'): ops.verify_files(root, allow_dry_run=True)
        self.assertNotEqual(self.node(root, '--check-only').returncode, 0)

    def test_prepare_failure_is_atomic(self):
        source = self.archive()
        with patch.object(ops, 'verify_files', side_effect=ValueError('simulated_verification_failure')):
            with self.assertRaisesRegex(ValueError, 'simulated_verification_failure'):
                release.prepare_rehearsal(source, self.root/'failed', self.clock, self.env)
        self.assertFalse((self.root/'failed').exists())
        self.assertFalse(any(p.name.startswith('.radar-release-') for p in self.root.iterdir()))

    def test_failure_notice_changes_ssr_but_preserves_data_snapshot_and_dates(self):
        baseline, original = self.rehearsal()
        destination = self.root/'failure'
        snapshot_bytes = (baseline/bundle.SNAPSHOT).read_bytes()
        history_bytes = (baseline/'history.json').read_bytes()
        real_verify = ops.verify_files
        # Exercise recovery rendering on an explicitly unpublishable diagnostic;
        # retain every content check and preserve its publication prohibition.
        with patch.object(ops, 'verify_files', side_effect=lambda root: real_verify(root, allow_dry_run=True)):
            ops.failure_release(baseline, destination, 'collect', '456', 'b'*40)
        manifest, data = real_verify(destination, allow_dry_run=True)
        self.assertEqual(data, self.data)
        self.assertEqual(manifest['dataSHA256'], original['dataSHA256'])
        self.assertEqual((destination/bundle.SNAPSHOT).read_bytes(), snapshot_bytes)
        self.assertEqual((destination/'history.json').read_bytes(), history_bytes)
        page = (destination/'public/index.html').read_text('utf-8')
        self.assertIn('class="pulse bad" id="pulse"', page)
        self.assertIn('本次更新未完成，显示', page)
        version = json.loads((destination/'public/version.json').read_bytes())
        self.assertEqual(version['generatedAt'], self.data['meta']['generatedAt'])
        self.assertEqual(version['state'], 'failed')
        import render_v3
        from release_schedule import schedule_metadata
        next_run = schedule_metadata({'cron_utc': data['meta']['schedule']['cronUtc']}, version['attemptedAt'])['nextRunAt']
        pulse = page.split('id="pulse"', 1)[1].split('</div>', 1)[0]
        self.assertIn('class="msg-bad"', pulse)
        self.assertNotIn('class="msg-warn"', pulse)
        self.assertIn('下次 <b class="num">' + render_v3.short_time(next_run, render_v3.date(data['meta']['today'])), pulse)
        self.assertEqual(self.node(destination, '--check-only').returncode, 0)
        with self.assertRaisesRegex(ValueError, 'diagnostic_publication_forbidden'): real_verify(destination)

    def test_failure_ssr_next_run_uses_recorded_attempt_and_has_no_clock_dependency(self):
        import render_v3
        today = render_v3.date(self.data['meta']['today'])
        original = copy.deepcopy(self.data)
        # Monday at the exact scheduled slot advances strictly to 08:45 Beijing.
        fragment = render_v3.render_pulse(self.data, today, {'state': 'failed', 'attemptedAt': '2026-10-26T06:50:00+08:00'})
        self.assertIn('class="msg-bad"', fragment)
        self.assertIn('下次 <b class="num">10/26 08:45</b>', fragment)
        fallback = render_v3.render_pulse(self.data, today, {'state': 'failed'})
        self.assertIn(render_v3.short_time(self.data['meta']['schedule']['nextRunAt'], today), fallback)
        self.assertEqual(self.data, original)

    def test_old_baseline_does_not_fetch_unversioned_snapshot(self):
        for version in (2, 3):
            names = []
            manifest = {'schemaVersion': version, 'sourceSHA': 'a'*40, 'dataSHA256': 'c'*64}
            def command(args, cwd=None):
                name = args[-1].split(':', 1)[1]
                names.append(name)
                return json.dumps(manifest).encode() if name == 'release.json' else b'{}'
            with patch.object(ops, 'api', return_value=[{'sha': 'b'*40}]), \
                    patch.object(ops, 'status', return_value={'state': 'success', 'productionSHA': 'b'*40}), \
                    patch.object(ops, 'command', side_effect=command), patch.object(ops, 'verify_files', return_value=(manifest, {})):
                ops.fetch_baseline(self.root/f'baseline-{version}')
            self.assertEqual(bundle.SNAPSHOT in names, version == 3)


if __name__ == '__main__':
    unittest.main()
