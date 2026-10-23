"""Both real release verifiers enforce threshold bounds on bound offline files."""
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
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import acceptance_bundle as bundle
import build
import daily_changes
import production_release as release
import release_operations as operations
from research_snapshot import canonical_json
from test_notion_v3 import run_fixture

MISSING = object()


class ScheduleVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = run_fixture()
        assert fixture['exit'] == 0, fixture['logs']
        cls.original = fixture['DATA']
        cls.snapshot = fixture['snapshot_object']
        assert cls.original['meta']['reviewPreview']

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.counter = 0
        network = patch.object(socket.socket, 'connect', side_effect=AssertionError('offline verifier test opened network'))
        self.network = network.start()
        self.addCleanup(network.stop)
        # Only benign runtime fields are forwarded, never the process's secrets.
        self.env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if key in os.environ}
        self.env.update(VERCEL_ENV='production', VERCEL_GIT_COMMIT_REF='production',
                        VERCEL_GIT_COMMIT_SHA='b' * 40)

    def artifact(self, threshold):
        self.counter += 1
        data = copy.deepcopy(self.original)
        if threshold is MISSING:
            data['meta']['schedule'].pop('lateAfterMinutes')
        else:
            data['meta']['schedule']['lateAfterMinutes'] = threshold
        clock = dt.datetime.fromisoformat(self.snapshot['builtAt'])
        receipt = {'schemaVersion': 1, 'purpose': 'offline-rehearsal',
            'execution': {'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'},
            'fixedClock': clock.isoformat(), 'publication': {
                'dataSHA256': bundle.data_digest(data), 'asOf': data['meta']['asOf'],
                'snapshot': data['meta']['snapshot'], 'blockers': build.release_blockers(data)}}
        source = self.root / f'bundle-{self.counter}'
        bundle.write_bundle(source, data, receipt, clock, research_snapshot=self.snapshot)
        info = {'schemaVersion': 1, 'state': 'current', 'sourceSHA': 'a' * 40,
            'runId': '123', 'dataSHA256': bundle.data_digest(data),
            'generatedAt': data['meta']['generatedAt'],
            'runUrl': f'https://github.com/{release.REPOSITORY}/actions/runs/123',
            'workflowUrl': operations.WORKFLOW, 'changes': daily_changes.summarize(data, [])}
        destination = self.root / f'release-{self.counter}'
        destination.mkdir()
        # Materialize fully bound files so an invalid threshold reaches each
        # verifier independently, rather than failing on a stale file hash.
        manifest = release._materialize(source, destination, data, receipt, info, [], 'offline-rehearsal')
        self.assertEqual(manifest['purpose'], 'offline-rehearsal')
        self.assertIs(manifest['publicationAuthorized'], False)
        self.assertTrue(data['meta']['reviewPreview'])
        self.assertIn('local_review_not_publishable', manifest['diagnosticBlockers'])
        self.assertEqual(bundle.embedded_data((destination / 'public/index.html').read_bytes()), data)
        self.assertEqual((destination / bundle.SNAPSHOT).read_bytes(), canonical_json(self.snapshot).encode())
        self.network.assert_not_called()
        return destination, data

    def node(self, destination, *, check=True):
        args = ['node', str(destination / 'verify-release.cjs')]
        if check:
            args.append('--check-only')
        return subprocess.run(args, cwd=destination, env=self.env, capture_output=True,
                              encoding='utf-8', timeout=60)

    def test_zero_and_180_verify_but_the_diagnostic_artifact_cannot_publish(self):
        for threshold in (0, 180):
            with self.subTest(threshold=threshold):
                destination, data = self.artifact(threshold)
                _, verified = operations.verify_files(destination, allow_dry_run=True)
                self.assertEqual(verified, data)
                checked = self.node(destination)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertIs(json.loads(checked.stdout)['verified'], True)
                with self.assertRaisesRegex(ValueError, 'diagnostic_publication_forbidden'):
                    operations.verify_files(destination)
                before = (destination / 'public/version.json').read_bytes()
                denied = self.node(destination, check=False)
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn('diagnostic_publication_forbidden', denied.stderr)
                self.assertEqual((destination / 'public/version.json').read_bytes(), before)

    def assert_threshold_rejected(self, threshold):
        destination, _ = self.artifact(threshold)
        before = (destination / 'public/version.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'invalid_schedule_threshold'):
            operations.verify_files(destination, allow_dry_run=True)
        checked = self.node(destination)
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn('release_schedule_missing', checked.stderr)
        self.assertEqual((destination / 'public/version.json').read_bytes(), before)

    def test_181_is_rejected_by_python_and_node_after_hash_binding_passes(self):
        self.assert_threshold_rejected(181)

    def test_missing_and_invalid_types_do_not_receive_a_default(self):
        for threshold in (MISSING, None, True, '180', 179.5):
            with self.subTest(threshold='missing' if threshold is MISSING else threshold):
                self.assert_threshold_rejected(threshold)


if __name__ == '__main__':
    unittest.main()
