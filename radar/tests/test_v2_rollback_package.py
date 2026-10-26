"""The packaged operator tool prepares local commits without publishing."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'radar/tools/v2_rollback'
spec = importlib.util.spec_from_file_location('prepare_v2_rollback', PACKAGE / 'prepare.py')
rollback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rollback)


class RollbackPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rollback-package-tests-')
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / 'repo'
        self.repo.mkdir()
        self.patch_path = self.repo / 'package.patch'
        self.patch_path.write_bytes((PACKAGE / 'v2-rollback-compatibility.patch').read_bytes())
        self.args = argparse.Namespace(repo=self.repo, patch=self.patch_path,
            merge='1' * 40, expected_v2_head='2' * 40, expected_pr4_head='4' * 40,
            rollback_baseline_sha='5' * 40)
        self.origin = 'https://github.com/lwd619783-byte/research-radar.git'
        self.dirty = ''
        self.head = self.args.merge
        self.parents = self.args.expected_v2_head + ' ' + self.args.expected_pr4_head
        self.manifest = {'schemaVersion': 2, 'blockers': []}
        self.changed = sorted(rollback.ALLOWED_V2_CHANGES)
        self.calls = []
        self.committed = False

    def git(self, repo, *args):
        self.assertEqual(repo, self.repo.resolve())
        self.calls.append(args)
        if args == ('rev-parse', '--show-toplevel'):
            return str(self.repo)
        if args == ('remote', 'get-url', 'origin'):
            return self.origin
        if args == ('status', '--porcelain'):
            return self.dirty
        if args == ('rev-parse', 'HEAD'):
            return 'a' * 40 if self.committed else self.head
        if args[:3] == ('show', '-s', '--format=%P'):
            return self.parents
        if args[:2] == ('merge-base', '--is-ancestor'):
            self.assertEqual(args[2:], (self.args.rollback_baseline_sha, 'origin/production'))
            return ''
        if args == ('show', self.args.rollback_baseline_sha + ':release.json'):
            return json.dumps(self.manifest)
        if args[0] == 'revert':
            self.assertEqual(args, ('revert', '--no-commit', '-m', '1', self.args.merge))
            self.patch_path.unlink()  # Reverting PR4 removes its own package.
            return ''
        if args[0] == 'apply':
            saved_patch = Path(args[-1])
            self.assertFalse(saved_patch.is_relative_to(self.repo))
            self.assertEqual(hashlib.sha256(saved_patch.read_bytes()).hexdigest(), rollback.PATCH_SHA256)
            if '--check' not in args:
                operations = self.repo / 'radar/scripts/release_operations.py'
                operations.parent.mkdir(parents=True)
                operations.write_text(rollback.PIN_SLOT + '\n', encoding='utf-8')
            return ''
        if args[0] == 'add':
            return ''
        if args[:3] == ('diff', '--cached', '--name-only'):
            return '\n'.join(self.changed)
        if args[0] == 'commit':
            self.assertNotIn('[skip ci]', args[-1])
            self.committed = True
            return ''
        self.fail('Unexpected Git action: ' + args[0])

    def prepare(self, runner=None):
        runner = runner or subprocess.CompletedProcess([], 0, '{"passed":true,"testsRun":26}', '')
        with patch.object(rollback, 'git', self.git), \
             patch.object(rollback.subprocess, 'run', return_value=runner):
            return rollback.prepare(self.args)

    def assert_no_mutation(self):
        self.assertFalse(any(args[0] in ('revert', 'apply', 'add', 'commit', 'push') for args in self.calls))

    def test_package_patch_is_pinned_and_changes_only_v2_operations_and_new_tests(self):
        blob = self.patch_path.read_bytes()
        self.assertEqual(hashlib.sha256(blob).hexdigest(), rollback.PATCH_SHA256)
        names = set(re.findall(r'^diff --git a/(\S+) b/\S+$', blob.decode(), re.M))
        self.assertEqual(names, rollback.ALLOWED_V2_CHANGES)

    def test_package_survives_its_own_revert_and_never_pushes_or_fetches(self):
        result = self.prepare()
        self.assertFalse(self.patch_path.exists())
        self.assertTrue(self.committed)
        self.assertEqual(result['testsPassed'], 26)
        self.assertEqual(result['preparedLocalCommit'], 'a' * 40)
        self.assertFalse(result['pushed'])
        self.assertFalse(result['deployed'])
        self.assertFalse(any(args[0] in ('push', 'fetch', 'clone') for args in self.calls))
        operation = (self.repo / 'radar/scripts/release_operations.py').read_text('utf-8')
        self.assertIn(self.args.rollback_baseline_sha, operation)

    def test_dirty_checkout_is_rejected_before_revert(self):
        self.dirty = ' M user-edit.py\n?? personal-notes.md'
        with self.assertRaisesRegex(ValueError, 'dirty checkout'):
            self.prepare()
        self.assert_no_mutation()

    def test_wrong_repository_is_rejected_without_echoing_remote_value(self):
        self.origin = 'https://github.com/someone/else.git'
        with self.assertRaisesRegex(ValueError, 'authorized research-radar repository'):
            self.prepare()
        self.assert_no_mutation()

    def test_changed_head_is_rejected(self):
        self.head = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'recorded PR4 merge'):
            self.prepare()
        self.assert_no_mutation()

    def test_wrong_parent_identity_is_rejected(self):
        self.parents = self.args.expected_pr4_head + ' ' + self.args.expected_v2_head
        with self.assertRaisesRegex(ValueError, 'parent binding mismatch'):
            self.prepare()
        self.assert_no_mutation()

    def test_short_sha_is_rejected_before_git(self):
        self.args.merge = '9338ec4'
        with self.assertRaisesRegex(ValueError, '40-character hashes'):
            self.prepare()
        self.assertEqual(self.calls, [])

    def test_tampered_patch_is_rejected_before_git(self):
        self.patch_path.write_text('invalid patch', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.prepare()
        self.assertEqual(self.calls, [])

    def test_v3_or_blocked_pinned_baseline_is_rejected(self):
        for manifest in ({'schemaVersion': 3, 'blockers': []}, {'schemaVersion': 2, 'blockers': ['stale']}):
            with self.subTest(manifest=manifest):
                self.manifest = manifest
                with self.assertRaisesRegex(ValueError, 'successful V2 manifest'):
                    self.prepare()
                self.assert_no_mutation()

    def test_unexpected_diff_prevents_commit_and_leaves_changes_for_review(self):
        self.changed.append('radar/data/notion_schema.json')
        with self.assertRaisesRegex(ValueError, 'Unexpected V2 differences'):
            self.prepare()
        self.assertFalse(self.committed)

    def test_failed_tests_prevent_commit_and_push(self):
        with patch.object(rollback, 'git', self.git), \
             patch.object(rollback.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['python'])):
            with self.assertRaises(subprocess.CalledProcessError):
                rollback.prepare(self.args)
        self.assertFalse(self.committed)
        self.assertFalse(any(args[0] == 'push' for args in self.calls))

    def test_empty_or_failed_test_receipt_prevents_commit(self):
        result = subprocess.CompletedProcess([], 0, '{"passed":false,"testsRun":0}', '')
        with self.assertRaisesRegex(ValueError, 'regression suite did not pass'):
            self.prepare(result)
        self.assertFalse(self.committed)


if __name__ == '__main__':
    unittest.main()
