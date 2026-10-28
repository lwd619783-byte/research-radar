"""Disabled templates and native schedule use the same four slot definitions."""
import datetime as dt
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/tools'))
import external_schedule_jobs as jobs
import schedule_admission as admission


class ExternalJobTests(unittest.TestCase):
    def test_four_disabled_templates_have_no_credentials_or_other_destinations(self):
        templates = jobs.job_templates()
        self.assertEqual({j['slot'] for j in templates}, set(admission.SLOTS))
        for entry in templates:
            job = entry['job']; self.assertIs(job['enabled'], False)
            self.assertIs(job['saveResponses'], False)
            self.assertIs(job['redirectSuccess'], False)
            self.assertEqual(job['requestMethod'], 1)
            self.assertEqual(job['schedule']['timezone'], 'Asia/Shanghai')
            self.assertEqual(job['schedule']['expiresAt'], 20261221000000)
            self.assertNotIn('Authorization', job['extendedData']['headers'])
            self.assertEqual(job['url'], 'https://api.github.com/repos/lwd619783-byte/research-radar/actions/workflows/radar-production.yml/dispatches')
            payload = json.loads(job['extendedData']['body'])
            self.assertEqual(payload['ref'], admission.SOURCE_BRANCH)
            self.assertEqual(payload['inputs']['trigger'], 'external_schedule')
            now = dt.datetime(2026, 11, 2, job['schedule']['hours'][0], job['schedule']['minutes'][0], tzinfo=admission.BJ)
            selected = admission.planned_slot('workflow_dispatch', payload, now, now)
            self.assertEqual(selected['slot'], entry['slot'])
            expected_days = [(day + 1) % 7 for day in admission.SLOTS[entry['slot']][3]]
            self.assertEqual(job['schedule']['wdays'], expected_days)


if __name__ == '__main__':
    unittest.main()
