"""Production admission failures must prevent creation of publishable output."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'radar/scripts'))
import production_release as release


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 21, 10, tzinfo=dt.UTC)
        self.env = {'GITHUB_REPOSITORY': release.REPOSITORY,
                    'GITHUB_REF': 'refs/heads/' + release.SOURCE_BRANCH,
                    'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_SHA': 'a'*40,
                    'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
        self.receipt = {'execution': self.env.copy(), 'fixedClock': self.now.isoformat(),
                        'publication': {'blockers': []}}
        self.data = {'meta': {}}

    def validate(self):
        with patch.object(release.bundle, 'validate_binding'), patch.object(release.build, 'release_blockers', return_value=[]):
            release.validate_release(self.data, self.receipt, self.now, self.env)

    def test_current_same_run_is_admitted(self):
        self.validate()

    def test_stale_future_and_different_execution_rejected(self):
        for seconds in (-1, 1801):
            self.receipt['fixedClock'] = (self.now-dt.timedelta(seconds=seconds)).isoformat()
            with self.assertRaisesRegex(ValueError, 'fresh'): self.validate()
        self.receipt['fixedClock'] = self.now.isoformat()
        self.receipt['execution']['GITHUB_SHA'] = 'b'*40
        with self.assertRaisesRegex(ValueError, 'mismatch'): self.validate()

    def test_wrong_repository_branch_event_and_rerun_rejected(self):
        for key, value in [('GITHUB_REPOSITORY', 'someone/else'), ('GITHUB_REF', 'refs/heads/production'),
                           ('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_RUN_ATTEMPT', '2')]:
            previous = self.env[key]
            self.env[key] = value
            with self.assertRaisesRegex(ValueError, 'not_allowed'): self.validate()
            self.env[key] = previous

    def test_synthetic_data_and_real_gate_failures_rejected(self):
        for flag in ('fixture', 'offline', 'reviewPreview'):
            self.data['meta'] = {flag: True}
            with self.assertRaisesRegex(ValueError, 'forbidden'): self.validate()
        self.data['meta'] = {}
        self.receipt['publication']['blockers'] = ['missing_price']
        with self.assertRaisesRegex(ValueError, 'blocked'): self.validate()
        self.receipt['publication']['blockers'] = []
        with patch.object(release.build, 'release_blockers', return_value=['missing_price']):
            with self.assertRaisesRegex(ValueError, 'blocked'):
                release.validate_release(self.data, self.receipt, self.now, self.env)

    def test_publish_is_after_checks_and_token_is_scoped(self):
        w = json.loads((ROOT/'.github/workflows/radar-production.yml').read_text('utf-8'))
        self.assertEqual(set(w['on']), {'schedule', 'push', 'workflow_dispatch'})
        self.assertEqual([x['cron'] for x in w['on']['schedule']],
                         ['45 0 * * 1-5', '15 4 * * 1-5', '15 10 * * 1-5', '50 22 * * 0'])
        steps = w['jobs']['refresh']['steps']
        self.assertFalse(steps[0]['with']['persist-credentials'])
        by_id = {s['id']: s for s in steps if 'id' in s}
        self.assertEqual({s['id'] for s in steps if 'GH_TOKEN' in s.get('env', {})}, {'baseline', 'publish', 'result'})
        self.assertTrue(all('GH_TOKEN' not in by_id[k].get('env', {}) for k in ('preflight','collect','prepare')))
        self.assertEqual({s['id'] for s in steps if 'NOTION_TOKEN' in s.get('env', {})}, {'collect'})
        self.assertIn('production_release.py', by_id['prepare']['run'])
        self.assertIn('--check-only', by_id['prepare']['run'])
        self.assertEqual(by_id['result']['if'], 'always()')
        self.assertEqual(steps[-1]['if'], 'always()')
        self.assertEqual(w['jobs']['refresh']['permissions']['statuses'], 'read')
        self.assertNotIn('secrets.VERCEL', json.dumps(w))
        for s in steps:
            if 'uses' in s: self.assertRegex(s['uses'], r'^actions/[a-z-]+@[0-9a-f]{40}$')


if __name__ == '__main__': unittest.main()
