"""Production and live dry-run have distinct admission and secret boundaries."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class V3WorkflowTests(unittest.TestCase):
    def load(self, name):
        return json.loads((ROOT / '.github/workflows' / name).read_text('utf-8'))

    def test_production_secret_only_enters_collector_and_publish_guards_remain(self):
        w = self.load('radar-production.yml')
        self.assertEqual(w['concurrency'], {'group': 'radar-production', 'cancel-in-progress': False, 'queue': 'max'})
        job = w['jobs']['refresh']
        for guard in ("github.repository == 'lwd619783-byte/research-radar'",
                      "github.ref == 'refs/heads/fix/radar-truthfulness-2026-10-18'", 'github.run_attempt == 1'):
            self.assertIn(guard, job['if'])
        steps = job['steps']; by_id = {s['id']: s for s in steps if 'id' in s}
        self.assertEqual([s.get('id') for s in steps if 'secrets.NOTION_TOKEN' in json.dumps(s)], ['collect'])
        self.assertEqual(by_id['collect']['env'], {'NOTION_TOKEN': '${{ secrets.NOTION_TOKEN }}'})
        self.assertIn('production_collect.py', by_id['collect']['run'])
        self.assertIn('--baseline', by_id['collect']['run'])
        self.assertNotIn('--live-dry-run', by_id['collect']['run'])
        self.assertIn('--check-only', by_id['prepare']['run'])
        self.assertEqual(by_id['publish']['run'], 'bash radar/scripts/publish_release.sh')
        self.assertLess(steps.index(by_id['collect']), steps.index(by_id['prepare']))
        self.assertLess(steps.index(by_id['prepare']), steps.index(by_id['publish']))
        self.assertNotIn('env', w); self.assertNotIn('env', job)

    def test_only_live_input_is_needed_and_manual_probe_still_needs_all_approvals(self):
        w = self.load('radar-interface-acceptance.yml')
        inputs = w['on']['workflow_dispatch']['inputs']
        self.assertEqual(inputs['live_notion']['type'], 'boolean')
        self.assertIs(inputs['live_notion']['default'], False)
        self.assertFalse(any(item.get('required') for item in inputs.values()))
        guard = w['jobs']['acceptance']['if']
        for part in ('inputs.zero_cost_verified == true', 'inputs.reviewed_sha == github.sha',
                     'inputs.live_notion != true', 'github.run_attempt == 1'):
            self.assertIn(part, guard)

    def test_live_job_cannot_publish_and_token_does_not_reach_later_steps(self):
        w = self.load('radar-interface-acceptance.yml'); job = w['jobs']['live_notion']
        self.assertEqual(w['permissions'], {'contents': 'read'})
        self.assertEqual(job['permissions'], {'contents': 'read', 'statuses': 'read'})
        for guard in ("github.event_name == 'workflow_dispatch'", 'inputs.live_notion == true',
                      "github.repository == 'lwd619783-byte/research-radar'",
                      "github.ref == 'refs/heads/v3/pr4-production'", 'github.run_attempt == 1'):
            self.assertIn(guard, job['if'])
        steps = job['steps']; by_id = {s['id']: s for s in steps if 'id' in s}
        self.assertEqual([s.get('id') for s in steps if 'secrets.NOTION_TOKEN' in json.dumps(s)], ['collect'])
        self.assertIn('--live-dry-run', by_id['collect']['run'])
        self.assertIn('live_notion_dry_run.py', by_id['verify']['run'])
        self.assertNotIn('env', by_id['verify'])
        for forbidden in ('publish_release.sh', 'git push', 'contents": "write', 'VERCEL_TOKEN'):
            self.assertNotIn(forbidden, json.dumps(job))
        upload = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact@'))
        self.assertEqual(upload['with']['name'], 'live-notion-dry-run')
        self.assertEqual(upload['with']['retention-days'], 7)
        self.assertFalse(upload['with']['include-hidden-files'])
        self.assertNotIn('notion-fetch', upload['with']['path'])
        for step in steps:
            if 'uses' in step:
                self.assertRegex(step['uses'], r'^actions/[a-z-]+@[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
