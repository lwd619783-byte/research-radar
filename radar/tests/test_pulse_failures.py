"""Known release failures take effect before a scheduled update becomes late."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PulseFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT / 'radar/site/app.js').read_text('utf-8')
        cls.helpers = (source[source.index('function nextScheduledRun('):source.index('function validVersion(')]
                       + source[source.index('function shortTime('):source.index('async function checkVersion(')])

    def render(self, operations, remote=None, *, warning=False, now='2026-10-21T10:00:00+08:00'):
        data = {'meta': {'generatedAt': '2026-10-21T08:45:00+08:00',
                        'schedule': {'nextRunAt': '2026-10-21T08:45:00+08:00',
                                     'lateAfterMinutes': 90,
                                     'cronUtc': ['45 0 * * 1-5', '15 4 * * 1-5', '15 10 * * 1-5']},
                        'notion': {'fallbackTables': [{'table': 'daily'}] if warning else []}}}
        setup = 'const D=' + json.dumps(data) + '; const OP=' + json.dumps(operations) + ';\n'
        setup += 'const remoteVersion=' + json.dumps(remote) + '; Date.now=()=>Date.parse(' + json.dumps(now) + ');\n'
        setup += "const TODAY='2026-10-21',CO=[],fin=Number.isFinite,esc=x=>String(x);\n"
        setup += "const box={className:'',innerHTML:''}, $=selector=>selector==='#pulse'?box:null;\n"
        script = setup + self.helpers + '\nrenderReleaseStatus(); process.stdout.write(JSON.stringify(box));'
        process = subprocess.run(['node', '-e', script], capture_output=True, encoding='utf-8')
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def operations(self, state='current'):
        return {'state': state, 'dataSHA256': 'a' * 64, 'sourceSHA': 'a' * 40,
                'generatedAt': '2026-10-21T08:45:00+08:00',
                'changes': {'mode': 'previous_update', 'today': {'reports': [], 'confirmed': [], 'scores': []}}}

    def assert_failure(self, output):
        self.assertEqual(output['className'], 'pulse bad')
        self.assertIn('class="dot bad"', output['innerHTML'])
        self.assertIn('本次更新未完成，显示 10/21 08:45 的数据', output['innerHTML'])
        self.assertIn('下次 10/21 12:15', output['innerHTML'])
        self.assertNotIn('今日变化', output['innerHTML'])
        self.assertNotIn('张研究表沿用', output['innerHTML'])

    def test_local_failure_is_immediate_and_overrides_warning(self):
        self.assert_failure(self.render(self.operations('failed'), warning=True))

    def test_remote_failure_for_same_data_is_immediate_without_refresh_requirement(self):
        ops = self.operations()
        output = self.render(ops, {**ops, 'state': 'failed'})
        self.assert_failure(output)
        self.assertNotIn('有新数据', output['innerHTML'])

    def test_remote_failure_for_same_data_with_new_source_is_failure_and_refresh(self):
        ops = self.operations()
        output = self.render(ops, {**ops, 'state': 'failed', 'sourceSHA': 'b' * 40})
        self.assert_failure(output)
        self.assertIn('有新数据', output['innerHTML'])

    def test_remote_failure_for_different_data_does_not_relabel_current_snapshot(self):
        ops = self.operations()
        output = self.render(ops, {**ops, 'state': 'failed', 'dataSHA256': 'b' * 64})
        self.assertEqual(output['className'], 'pulse ok')
        self.assertIn('今日变化：财报 0', output['innerHTML'])
        self.assertIn('有新数据', output['innerHTML'])
        self.assertNotIn('本次更新未完成', output['innerHTML'])

    def test_no_failure_stays_current_before_delay_window_and_late_still_turns_red(self):
        self.assertEqual(self.render(self.operations())['className'], 'pulse ok')
        self.assert_failure(self.render(self.operations(), now='2026-10-21T10:15:01+08:00'))


if __name__ == '__main__':
    unittest.main()
