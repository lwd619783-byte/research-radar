"""The published deadline and Actions timetable describe the same clock."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
from release_schedule import schedule_metadata
from schema import load_and_validate


class ScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = tomllib.loads((ROOT / 'radar/data/config.toml').read_text('utf-8'))

    def test_config_matches_production_schedule_and_defaults_to_notion(self):
        workflow = json.loads((ROOT / '.github/workflows/radar-production.yml').read_text('utf-8'))
        self.assertEqual(self.config['schedule']['cron_utc'],
                         [row['cron'] for row in workflow['on']['schedule']])
        self.assertEqual(self.config['build']['source'], 'notion')

    def test_toml_loader_preserves_schedule_for_build(self):
        data, report = load_and_validate(ROOT / 'radar', ROOT, dt.date(2026, 10, 21))
        self.assertEqual(report.errors, [])
        self.assertEqual(data['config']['schedule'], self.config['schedule'])
        self.assertEqual(schedule_metadata(data['config'], '2026-10-23T18:15:00+08:00'), {
            'cronUtc': self.config['schedule']['cron_utc'],
            'nextRunAt': '2026-10-26T06:50:00+08:00',
            'lateAfterMinutes': 180,
        })

    def test_next_run_at_weekday_friday_sunday_and_week_boundary(self):
        cases = {
            '2026-10-21T18:15:00+08:00': '2026-10-22T08:45:00+08:00',
            '2026-10-23T18:15:00+08:00': '2026-10-26T06:50:00+08:00',
            '2026-10-25T12:00:00+08:00': '2026-10-26T06:50:00+08:00',
            '2026-10-26T06:49:59+08:00': '2026-10-26T06:50:00+08:00',
            '2026-10-26T06:50:00+08:00': '2026-10-26T08:45:00+08:00',
            '2026-12-31T18:15:00+08:00': '2027-01-01T08:45:00+08:00',
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                result = schedule_metadata(self.config, source)
                self.assertEqual(result['nextRunAt'], expected)
                self.assertEqual(result['lateAfterMinutes'], 180)
                self.assertEqual(schedule_metadata(self.config, dt.datetime.fromisoformat(source)), result)
        self.assertEqual(schedule_metadata(self.config, '2026-10-21T10:15:00Z'),
                         schedule_metadata(self.config, '2026-10-21T18:15:00+08:00'))

    def test_absent_config_and_invalid_clock_or_cron(self):
        self.assertIsNone(schedule_metadata({}, '2026-10-21T18:15:00+08:00'))
        self.assertIsNone(schedule_metadata({'build': {'source': 'toml'}}, 'unused'))
        with self.assertRaisesRegex(ValueError, 'without_timezone'):
            schedule_metadata(self.config, '2026-10-21T18:15:00')
        for expression in ('60 0 * * 1-5', '0 24 * * 0', '0 0 * * 5-1', '0 0 * * 7', '* * * * *'):
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, 'invalid_schedule'):
                schedule_metadata({'cron_utc': [expression]}, '2026-10-21T18:15:00+08:00')
        with self.assertRaisesRegex(ValueError, 'invalid_schedule'):
            schedule_metadata({'cron_utc': []}, '2026-10-21T18:15:00+08:00')

    def test_browser_and_build_agree_after_deadline_and_at_exact_cron(self):
        source = (ROOT / 'radar/site/app.js').read_text('utf-8')
        helper = source[source.index('function nextScheduledRun('):source.index('function scheduledDue(')]
        clocks = ['2026-10-23T18:15:00+08:00', '2026-10-26T08:21:00+08:00', '2026-10-26T08:45:00+08:00']
        expected = [schedule_metadata(self.config, value)['nextRunAt'] for value in clocks]
        script = helper + '\nconst crons=' + json.dumps(self.config['schedule']['cron_utc']) + ';\n'
        script += 'const clocks=' + json.dumps(clocks) + '; const expected=' + json.dumps(expected) + ';\n'
        script += "clocks.forEach((value,i)=>require('node:assert/strict').equal(nextScheduledRun(crons,Date.parse(value)),Date.parse(expected[i])));"
        run = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
