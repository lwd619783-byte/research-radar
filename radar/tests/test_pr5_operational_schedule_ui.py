"""A queued collection must not swallow the next scheduled UI deadline."""
import copy
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import release_schedule
import render_v3


class OperationalScheduleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = tomllib.loads((ROOT / 'radar/data/config.toml').read_text('utf-8'))
        source = (ROOT / 'radar/site/app.js').read_text('utf-8')
        cls.helpers = (
            source[source.index('function nextScheduledRun('):source.index('function validVersion(')]
            + source[source.index('function shortTime('):source.index('async function checkVersion(')]
        )
        cls.esc = next(line for line in source.splitlines() if line.startswith('const esc='))

    def setUp(self):
        # The 08:45 run was queued until 13:00. Collection metadata describes
        # 18:15, while trusted publication ownership still requires 12:15.
        self.data = {'meta': {'generatedAt': '2026-10-23T13:00:00+08:00',
            'schedule': release_schedule.schedule_metadata(self.config, '2026-10-23T13:00:00+08:00')},
            'companies': []}
        self.operations = {'state': 'current', 'generatedAt': self.data['meta']['generatedAt'],
            'dataSHA256': 'a' * 64, 'sourceSHA': 'b' * 40,
            'schedule': release_schedule.schedule_metadata(self.config, '2026-10-23T08:45:00+08:00')}
        self.before = copy.deepcopy(self.data)
        self.today = dt.date(2026, 10, 23)

    def render_js(self, operations, now):
        setup = 'const D=' + json.dumps(self.data) + ',OP=' + json.dumps(operations) + ';\n'
        setup += 'Date.now=()=>Date.parse(' + json.dumps(now) + ');\n'
        setup += "const TODAY='2026-10-23',CO=[],remoteVersion=null,fin=Number.isFinite;\n"
        setup += self.esc + '\n'
        setup += "const box={className:'',innerHTML:''},$=selector=>selector==='#pulse'?box:null;\n"
        script = setup + self.helpers + '\nrenderReleaseStatus();process.stdout.write(JSON.stringify({box,data:D}));'
        result = subprocess.run(['node', '-e', script], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['data'], self.before)
        return output['box']

    def test_ssr_and_js_show_owned_next_slot_without_rewriting_data_clock(self):
        self.assertEqual(self.data['meta']['schedule']['nextRunAt'], '2026-10-23T18:15:00+08:00')
        self.assertEqual(self.operations['schedule']['nextRunAt'], '2026-10-23T12:15:00+08:00')
        markup = render_v3.render_pulse(self.data, self.today, self.operations)
        self.assertIn('10/23 12:15', markup)
        self.assertNotIn('10/23 18:15', markup)
        self.assertIn('10/23 13:00', markup)
        result = self.render_js(self.operations, '2026-10-23T13:00:00+08:00')
        self.assertEqual(result['className'], 'pulse ok')
        self.assertIn('下次 10/23 12:15', result['innerHTML'])
        self.assertIn('行情更新于 10/23 13:00', result['innerHTML'])
        self.assertEqual(self.data, self.before)

    def test_owned_slot_turns_red_only_after_180_and_stays_red_across_slots(self):
        for clock, expected in (
            ('2026-10-23T15:14:00+08:00', 'pulse ok'),
            ('2026-10-23T15:15:00+08:00', 'pulse ok'),
            ('2026-10-23T15:15:01+08:00', 'pulse bad'),
            ('2026-10-23T18:15:00+08:00', 'pulse bad'),
            ('2026-10-26T08:45:00+08:00', 'pulse bad'),
        ):
            with self.subTest(clock=clock):
                output = self.render_js(self.operations, clock)
                self.assertEqual(output['className'], expected)
                if expected == 'pulse bad':
                    self.assertIn('本次更新未完成，显示 10/23 13:00 的数据', output['innerHTML'])
                    self.assertNotIn('今日变化', output['innerHTML'])

    def test_known_failure_remains_immediate_and_advances_displayed_next_plan(self):
        self.operations.update(state='failed', attemptedAt='2026-10-23T13:01:00+08:00')
        markup = render_v3.render_pulse(self.data, self.today, self.operations)
        self.assertIn('class="dot bad"', markup)
        self.assertIn('本次更新未完成', markup)
        self.assertIn('10/23 18:15', markup)
        self.assertNotIn('10/23 12:15', markup)
        output = self.render_js(self.operations, '2026-10-23T13:01:00+08:00')
        self.assertEqual(output['className'], 'pulse bad')
        self.assertIn('下次 10/23 18:15', output['innerHTML'])
        self.assertNotIn('今日变化', output['innerHTML'])
        self.assertEqual(self.data, self.before)

    def test_legacy_operations_without_schedule_keep_bound_data_schedule(self):
        self.operations.pop('schedule')
        for operations in (None, self.operations):
            with self.subTest(operations=operations):
                markup = render_v3.render_pulse(self.data, self.today, operations)
                self.assertIn('10/23 18:15', markup)
                self.assertNotIn('10/23 12:15', markup)
                output = self.render_js(operations, '2026-10-23T15:15:01+08:00')
                self.assertEqual(output['className'], 'pulse ok')
                self.assertIn('下次 10/23 18:15', output['innerHTML'])
        self.assertEqual(self.data, self.before)


if __name__ == '__main__':
    unittest.main()
