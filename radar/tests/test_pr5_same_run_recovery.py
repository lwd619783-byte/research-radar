"""A late deployment receipt cannot make the same run undo its data push.

Independent synthetic releases reproduce the 42080047176 control flow. Git and
GitHub are transports only: finish, failure materialization, the freshly fetched
HEAD checks, both file verifiers and publication admission all execute unchanged.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_pr5_queued_runs as queued

operations = queued.operations


class SameRunRecoveryTests(queued.PublishHarness):
    def setUp(self):
        super().setUp()
        self.env.update(GITHUB_STEP_SUMMARY=str(self.base/'summary.md'),
                        SCHEDULE_ADMISSION='allowed')
        self.outcomes = dict.fromkeys(('baseline', 'preflight', 'collect', 'prepare', 'publish'), 'success')
        self.deployment = {'state': 'success', 'productionSHA': 'd' * 40,
                           'deploymentUrl': operations.DEPLOY_PREFIX + 'SyntheticDeployment'}

    def transport(self, args, cwd=None):
        result = super().transport(args, cwd)
        if args[:2] == ['git', 'push']:
            # Model the successful push. A later fetch must see this exact new
            # release, not the baseline captured before collection started.
            self.current = Path(cwd)
        return result

    def finish(self, outcomes, production_sha):
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(operations, 'api', side_effect=self.api), \
                patch.object(operations, 'command', side_effect=self.transport), \
                contextlib.redirect_stdout(io.StringIO()):
            return operations.finish(self.base, outcomes, production_sha)

    def node_check(self, root):
        env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if key in os.environ}
        before = (root/'public/version.json').read_bytes()
        checked = subprocess.run(['node', str(queued.ROOT/'radar/scripts/verify-release.cjs'), '--check-only'],
                                 cwd=root, env=env, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)['verified'])
        self.assertEqual((root/'public/version.json').read_bytes(), before)

    def publication_count(self, verb):
        return sum(args[:2] == ['git', verb] for args in self.calls)

    def test_same_run_push_then_timeout_and_late_ready_never_commits_old_baseline(self):
        queued.make_release(self.current, '08:30', '123')
        shutil.copytree(self.current, self.base/'radar-baseline')
        _, new_data = queued.make_release(self.candidate, '13:00')
        pushed_sha = self.publish()
        published = self.current
        before = {name: (published/name).read_bytes() for name in
                  ('public/index.html', 'public/version.json', 'release.json', 'history.json')}
        self.assertEqual(self.publication_count('commit'), 1)
        self.assertEqual(self.publication_count('push'), 1)

        rejected = []
        real_guard = operations.prevent_publication_regression
        def guard(*args):
            try:
                return real_guard(*args)
            except ValueError as error:
                rejected.append(str(error))
                raise

        # First observation is still pending at the 300-second deadline. The
        # same deployment becomes READY later, exactly the incident's ordering.
        with patch.object(operations, 'status', side_effect=[{'state': 'pending'}, self.deployment]) as status, \
                patch.object(operations.time, 'monotonic', side_effect=[0, 301, 302]), \
                patch.object(operations, 'protection_check', return_value=[{'protected': True}]), \
                patch.object(operations, 'prevent_publication_regression', side_effect=guard):
            result = self.finish(self.outcomes, pushed_sha)
            self.assertEqual(status.call_count, 1)
            self.assertEqual(rejected, ['publication_older_than_production'])
            self.assertEqual(result['failedStage'], 'deployment')
            self.assertEqual(result['recovery']['state'], 'unavailable')
            self.assertEqual(self.publication_count('commit'), 1)
            self.assertEqual(self.publication_count('push'), 1)
            late_receipt = operations.wait_deployment(pushed_sha)
            self.assertEqual(late_receipt['state'], 'success')
            self.assertEqual(late_receipt['productionSHA'], pushed_sha)

        self.assertEqual(self.current, published)
        for name, expected in before.items():
            self.assertEqual((published/name).read_bytes(), expected, name)
        manifest, actual = operations.verify_files(published)
        self.assertEqual(actual, new_data)
        self.assertEqual(manifest['fixedClock'], '2026-11-02T13:00:00+08:00')
        self.assertEqual(actual['meta']['generatedAt'], '2026-11-02T13:00:00+08:00')
        self.assertEqual(manifest['runId'], '456')
        self.assertEqual(json.loads((published/'public/version.json').read_text('utf-8'))['state'], 'current')
        self.node_check(published)

    def test_failure_before_data_push_keeps_baseline_and_publishes_bounded_notice(self):
        baseline_manifest, old_data = queued.make_release(self.current, '08:30', '123')
        old_history = (self.current/'history.json').read_bytes()
        shutil.copytree(self.current, self.base/'radar-baseline')
        outcomes = self.outcomes | {'collect': 'failure', 'prepare': 'skipped', 'publish': 'skipped'}
        with patch.object(operations, 'status', return_value=self.deployment), \
                patch.object(operations, 'protection_check', return_value=[{'protected': True}]):
            result = self.finish(outcomes, '')

        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['failedStage'], 'collect')
        self.assertEqual(result['recovery']['state'], 'success')
        self.assertEqual(self.publication_count('commit'), 1)
        self.assertEqual(self.publication_count('push'), 1)
        manifest, actual = operations.verify_files(self.current)
        version = json.loads((self.current/'public/version.json').read_text('utf-8'))
        self.assertEqual(actual, old_data)
        self.assertEqual(manifest['fixedClock'], baseline_manifest['fixedClock'])
        self.assertEqual(manifest['dataSHA256'], baseline_manifest['dataSHA256'])
        self.assertEqual(manifest['runId'], '123')
        self.assertEqual((self.current/'history.json').read_bytes(), old_history)
        self.assertEqual(version['state'], 'failed')
        self.assertEqual(version['failedStage'], 'collect')
        self.assertEqual(version['attemptRunId'], '456')
        self.node_check(self.current)


if __name__ == '__main__':
    unittest.main()
