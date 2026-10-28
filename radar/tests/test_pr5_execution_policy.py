"""Additional live refs remain exact, read-only, and bound to workflow code."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import execution_policy as policy
import production_collect as collect


class RehearsalAdmissionTests(unittest.TestCase):
    def env(self, branch):
        ref = 'refs/heads/' + branch
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': policy.REPOSITORY,
                'GITHUB_REF': ref, 'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123',
                'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW_REF': policy.REPOSITORY + '/' + policy.LIVE_WORKFLOW + '@' + ref,
                'GITHUB_WORKFLOW_SHA': 'a' * 40}

    def test_exact_new_refs_with_matching_workflow_can_collect_diagnostics(self):
        for branch in (policy.SOURCE_BRANCH, policy.PREPARATION_BRANCH):
            with self.subTest(branch=branch):
                collect.admit(self.env(branch), live_dry_run=True)

    def test_new_refs_reject_missing_or_other_workflow_and_other_commit(self):
        for branch in (policy.SOURCE_BRANCH, policy.PREPARATION_BRANCH):
            for key, value in (('GITHUB_WORKFLOW_REF', ''), ('GITHUB_WORKFLOW_SHA', 'b' * 40),
                               ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_RUN_ATTEMPT', '2'),
                               ('GITHUB_REPOSITORY', 'someone/research-radar'),
                               ('GITHUB_REF', 'refs/heads/v3/pr5-unreviewed')):
                env = self.env(branch); env[key] = value
                with self.subTest(branch=branch, key=key), self.assertRaises(collect.CollectError):
                    collect.admit(env, live_dry_run=True)

    def test_pr5_is_never_a_production_ref(self):
        with self.assertRaises(collect.CollectError):
            collect.admit(self.env(policy.PREPARATION_BRANCH))

    def test_workflow_permits_exact_refs_without_write_permissions_or_publish_step(self):
        workflow = json.loads((ROOT / '.github/workflows/radar-interface-acceptance.yml').read_text('utf-8'))
        job = workflow['jobs']['live_notion']
        for branch in (policy.SOURCE_BRANCH, policy.PREPARATION_BRANCH):
            self.assertIn("github.ref == 'refs/heads/" + branch + "'", job['if'])
        self.assertEqual(job['permissions'], {'contents': 'read', 'statuses': 'read'})
        serialized = json.dumps(job)
        for value in ('publish_release.sh', 'git push', 'contents": "write'):
            self.assertNotIn(value, serialized)
        identity = next(s['run'] for s in job['steps'] if s.get('name') == 'Validate dry-run identity')
        self.assertIn('GITHUB_WORKFLOW_REF', identity)
        self.assertIn('GITHUB_WORKFLOW_SHA', identity)


if __name__ == '__main__':
    unittest.main()
