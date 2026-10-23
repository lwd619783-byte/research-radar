"""New live refs exercise the full diagnostic chain without laundering fixtures.

The positive offline path uses prepare_rehearsal, preserves reviewPreview and
exports an explicitly offline result. The real live helper must still reject the
same fixture input. A passing local regression is never a live-data readiness
receipt.
"""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import acceptance_bundle as bundle
import build
import execution_policy as policy
import live_notion_dry_run as live
import production_collect as collect
import production_release as release
import release_operations as operations
from research_snapshot import canonical_json
from test_notion_v3 import run_fixture


class NewRefDiagnosticIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = run_fixture()
        assert fixture['exit'] == 0, fixture['logs']
        cls.original = fixture['DATA']
        cls.original_snapshot = fixture['snapshot_object']
        cls.node = shutil.which('node')
        assert cls.node, 'Node is required to verify the production rejection boundary'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = copy.deepcopy(self.original)
        self.snapshot = copy.deepcopy(self.original_snapshot)
        self.clock = dt.datetime.fromisoformat(self.snapshot['builtAt'])
        self.assertTrue(self.data['meta']['reviewPreview'])
        self.receipt = {'schemaVersion': 1, 'purpose': 'offline-rehearsal',
            'execution': {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'},
            'fixedClock': self.clock.isoformat(), 'publication': {
                'dataSHA256': bundle.data_digest(self.data),
                'asOf': self.data['meta']['asOf'], 'snapshot': self.data['meta']['snapshot'],
                'blockers': build.release_blockers(self.data)}}
        self.archive = self.root / 'archive'
        bundle.write_bundle(self.archive, self.data, self.receipt, self.clock, research_snapshot=self.snapshot)
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('integration regression opened network'))
        self.network = network.start()
        self.addCleanup(network.stop)

    def env(self, branch):
        ref = 'refs/heads/' + branch
        # Explicit allowlist: do not copy process credentials into subprocesses.
        env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if key in os.environ}
        env.update(GITHUB_ACTIONS='true', GITHUB_REPOSITORY=policy.REPOSITORY,
                   GITHUB_REF=ref, GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_SHA='a' * 40,
                   GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='1',
                   GITHUB_WORKFLOW_REF=policy.REPOSITORY + '/' + policy.LIVE_WORKFLOW + '@' + ref,
                   GITHUB_WORKFLOW_SHA='a' * 40)
        return env

    def test_matching_refs_prepare_verify_and_export_only_offline_diagnostics(self):
        for index, branch in enumerate((policy.SOURCE_BRANCH, policy.PREPARATION_BRANCH)):
            with self.subTest(branch=branch):
                env = self.env(branch)
                collect.admit(env, live_dry_run=True)
                destination = self.root / f'release-{index}'
                manifest = release.prepare_rehearsal(self.archive, destination, now=self.clock, env=env)
                self.assertEqual(manifest['purpose'], 'offline-rehearsal')
                self.assertIs(manifest['publicationAuthorized'], False)
                self.assertEqual(manifest['sourceSHA'], env['GITHUB_SHA'])
                _, data = operations.verify_files(destination, allow_dry_run=True)
                self.assertEqual(data, self.data)
                self.assertTrue(data['meta']['reviewPreview'])
                self.assertEqual((destination / bundle.SNAPSHOT).read_bytes(), canonical_json(self.snapshot).encode())

                checked = subprocess.run([self.node, 'verify-release.cjs', '--check-only'],
                    cwd=destination, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                result = {'ready': False, 'verified': True, 'publicationAuthorized': False,
                          'purpose': 'offline-rehearsal', 'code': 'offline_rehearsal_only'}
                artifact = self.root / f'artifact-{index}'
                names = live.export_artifact(artifact, data=data, snapshot=self.snapshot,
                    result=result, summary=collect.step_summary(data))
                self.assertEqual(set(names), {'result.json', 'meta.notion.json', 'meta.weekly.json',
                                             'meta.daily.json', bundle.SNAPSHOT, 'step-summary.md'})
                self.assertEqual(json.loads((artifact / 'result.json').read_text('utf-8')), result)
                self.assertEqual((artifact / bundle.SNAPSHOT).read_bytes(), (destination / bundle.SNAPSHOT).read_bytes())
                self.assertFalse(any(path.name in {'index.html', 'vercel.json', 'release.json', 'verify-release.cjs'}
                                     for path in artifact.rglob('*')))

                version = (destination / 'public/version.json').read_bytes()
                denied = subprocess.run([self.node, 'verify-release.cjs'], cwd=destination,
                    env=env | {'VERCEL_ENV': 'production', 'VERCEL_GIT_COMMIT_REF': 'production',
                               'VERCEL_GIT_COMMIT_SHA': 'b' * 40},
                    capture_output=True, text=True, encoding='utf-8', timeout=60)
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn('diagnostic_publication_forbidden', denied.stderr)
                self.assertEqual((destination / 'public/version.json').read_bytes(), version)
                with self.assertRaisesRegex(ValueError, 'diagnostic_publication_forbidden'):
                    operations.verify_files(destination)
                with self.assertRaisesRegex(ValueError, 'diagnostic_publication_forbidden'):
                    release.prepare(self.archive, self.root / f'production-{index}', now=self.clock, env=env)
        self.network.assert_not_called()

    def test_missing_or_wrong_workflow_identity_cannot_prepare_or_export(self):
        changes = [('GITHUB_WORKFLOW_REF', None), ('GITHUB_WORKFLOW_SHA', None),
                   ('GITHUB_WORKFLOW_REF', policy.REPOSITORY + '/.github/workflows/radar-production.yml'),
                   ('GITHUB_WORKFLOW_SHA', 'b' * 40)]
        for branch in (policy.SOURCE_BRANCH, policy.PREPARATION_BRANCH):
            for key, value in changes:
                with self.subTest(branch=branch, key=key, value=value):
                    env = self.env(branch)
                    if value is None:
                        env.pop(key)
                    else:
                        env[key] = value
                    destination = self.root / 'rejected-release'
                    artifact = self.root / 'rejected-artifact'
                    with self.assertRaisesRegex(ValueError, 'dry_run_execution_not_allowed'):
                        release.prepare_rehearsal(self.archive, destination, now=self.clock, env=env)
                    with self.assertRaisesRegex(ValueError, 'collection_execution_not_allowed'):
                        live.verify(source=self.archive, destination=destination, artifact=artifact,
                                    now=self.clock, env=env, node=self.node)
                    self.assertFalse(destination.exists())
                    self.assertFalse(artifact.exists())
        self.network.assert_not_called()

    def test_matching_new_refs_do_not_turn_fixture_into_real_live_readiness(self):
        for index, branch in enumerate((policy.SOURCE_BRANCH, policy.PREPARATION_BRANCH)):
            with self.subTest(branch=branch):
                env = self.env(branch)
                destination = self.root / f'live-release-{index}'
                artifact = self.root / f'live-artifact-{index}'
                with self.assertRaisesRegex(ValueError, 'dry_run_market_gate_failed|real_input'):
                    release.prepare_dry_run(self.archive, destination, now=self.clock, env=env)
                with patch.object(live.subprocess, 'run') as node:
                    result = live.verify(source=self.archive, destination=destination, artifact=artifact,
                                         now=self.clock, env=env, node=self.node)
                    node.assert_not_called()
                self.assertFalse(result['ready'])
                self.assertFalse(result['verified'])
                self.assertIs(result['publicationAuthorized'], False)
                self.assertEqual(result['code'], 'release_verification_failed')
                self.assertFalse(destination.exists())
                saved = json.loads((artifact / 'result.json').read_text('utf-8'))
                self.assertFalse(saved['ready'])
                self.assertIs(saved['publicationAuthorized'], False)
                self.assertTrue(json.loads((self.archive / 'DATA.json').read_text('utf-8'))['meta']['reviewPreview'])
        self.network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
