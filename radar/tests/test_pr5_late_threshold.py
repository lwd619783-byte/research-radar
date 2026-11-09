"""Configured delay flows through real build metadata without a numeric fallback."""
import copy
import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import build
import release_schedule as schedule
import render_v3
from schema import load_and_validate


class LateThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clock = dt.datetime.fromisoformat('2026-10-23T18:15:00+08:00')
        cls.loaded, report = load_and_validate(ROOT / 'radar', ROOT, cls.clock.date())
        assert not report.errors, report.errors
        cls.crons = cls.loaded['config']['schedule']['cron_utc']

    def assembled(self):
        # Exercise the production assembler's metadata boundary without market
        # requests or invented success evidence. This is not a release packet.
        data = copy.deepcopy(self.loaded)
        data.update(companies=[], industries=[], chokepoints=[])
        data['config']['indices'] = []
        market = {key: {} for key in ('daily', 'quote', 'index', 'fx', 'ratio')}
        result, _, _ = build.assemble(data, market, market, self.clock)
        return result

    def due(self, metadata, clocks):
        source = (ROOT / 'radar/site/app.js').read_text('utf-8')
        helper = source[source.index('function scheduledDue('):source.index('function validVersion(')]
        script = helper + '\nconst schedule=' + json.dumps(metadata) + ';'
        script += '\nconst clocks=' + json.dumps(clocks) + ';'
        script += '\nprocess.stdout.write(JSON.stringify(clocks.map(now=>scheduledDue("2026-10-23T18:15:00+08:00",Date.parse(now),schedule))));'
        result = subprocess.run(['node', '-e', script], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_real_toml_loader_and_assembler_publish_the_configured_180(self):
        result = self.assembled()
        self.assertEqual(self.loaded['config']['schedule']['late_after_minutes'], 180)
        self.assertEqual(result['meta']['schedule'], {
            'cronUtc': self.crons, 'nextRunAt': '2026-10-26T06:50:00+08:00',
            'lateAfterMinutes': self.loaded['config']['schedule']['late_after_minutes'],
        })

    def test_built_deadline_is_not_late_at_179_or_180_but_is_after_180(self):
        metadata = self.assembled()['meta']['schedule']
        planned = dt.datetime.fromisoformat(metadata['nextRunAt'])
        clocks = [(planned + delta).isoformat() for delta in (
            dt.timedelta(minutes=179), dt.timedelta(minutes=180),
            dt.timedelta(minutes=180, seconds=1), dt.timedelta(minutes=181))]
        self.assertEqual(self.due(metadata, clocks), [False, False, True, True])

    def test_no_new_success_keeps_original_overdue_slot_across_later_slots(self):
        metadata = self.assembled()['meta']['schedule']
        original = copy.deepcopy(metadata)
        clocks = ['2026-10-26T09:50:01+08:00', '2026-10-26T12:15:00+08:00',
                  '2026-10-26T18:15:00+08:00', '2026-10-27T08:45:00+08:00']
        self.assertEqual(self.due(metadata, clocks), [True] * len(clocks))
        self.assertEqual(metadata, original)

    def test_known_failure_ssr_stays_red_with_configured_schedule(self):
        data = self.assembled()
        for attempted in ('2026-10-26T06:51:00+08:00', '2026-10-26T09:50:01+08:00',
                          '2026-10-27T08:45:00+08:00'):
            with self.subTest(attempted=attempted):
                markup = render_v3.render_pulse(data, self.clock.date(),
                    {'state': 'failed', 'attemptedAt': attempted})
                self.assertIn('class="dot bad"', markup)
                self.assertIn('class="msg-bad">本次更新未完成', markup)
                self.assertNotIn('今日变化', markup)

    def test_cron_only_legacy_calls_read_the_authoritative_file_each_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            with patch.object(schedule, 'CONFIG_PATH', path):
                for value in (120, 180):
                    path.write_text('[schedule]\nlate_after_minutes = ' + str(value) + '\n', encoding='utf-8')
                    result = schedule.schedule_metadata({'cron_utc': self.crons}, self.clock)
                    self.assertEqual(result['lateAfterMinutes'], value)
                    self.assertEqual(result['nextRunAt'], '2026-10-26T06:50:00+08:00')

    def test_missing_malformed_and_out_of_range_authoritative_config_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            with patch.object(schedule, 'CONFIG_PATH', path):
                with self.assertRaisesRegex(ValueError, 'invalid_schedule_threshold'):
                    schedule.schedule_metadata({'cron_utc': self.crons}, self.clock)
                for content in ('', '[schedule]\n', '[schedule]\nlate_after_minutes =',
                                '[schedule]\nlate_after_minutes = 181\n',
                                '[schedule]\nlate_after_minutes = true\n'):
                    with self.subTest(content=content):
                        path.write_text(content, encoding='utf-8')
                        with self.assertRaisesRegex(ValueError, 'invalid_schedule_threshold'):
                            schedule.schedule_metadata({'cron_utc': self.crons}, self.clock)

    def test_explicit_invalid_threshold_never_falls_back_to_another_value(self):
        with patch.object(schedule, 'configured_late_after_minutes', side_effect=AssertionError('unexpected fallback')):
            for value in (None, True, False, -1, 181, 180.0, '180'):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid_schedule_threshold'):
                    schedule.schedule_metadata({'cron_utc': self.crons, 'late_after_minutes': value}, self.clock)
            self.assertEqual(schedule.schedule_metadata({'cron_utc': self.crons,
                'late_after_minutes': 0}, self.clock)['lateAfterMinutes'], 0)

    def test_schema_check_validates_its_own_file_without_borrowing_production_default(self):
        original = (ROOT / 'radar/data/config.toml').read_text('utf-8')
        with tempfile.TemporaryDirectory() as directory:
            radar = Path(directory) / 'radar'
            (radar / 'data').mkdir(parents=True)
            for name in ('industries.toml', 'chokepoints.toml', 'companies.toml'):
                shutil.copyfile(ROOT / 'radar/data' / name, radar / 'data' / name)
            for replacement in ('', 'late_after_minutes = 181', 'late_after_minutes = true',
                                'late_after_minutes = "180"', 'late_after_minutes = -1',
                                'late_after_minutes = 180.0'):
                with self.subTest(replacement=replacement):
                    (radar / 'data/config.toml').write_text(
                        original.replace('late_after_minutes = 180', replacement), encoding='utf-8')
                    with patch.object(schedule, 'configured_late_after_minutes', side_effect=AssertionError('unexpected fallback')):
                        _, report = load_and_validate(radar, ROOT, self.clock.date())
                    self.assertTrue(any('config.toml [schedule]' in error for error in report.errors), report.errors)


if __name__ == '__main__':
    unittest.main()
