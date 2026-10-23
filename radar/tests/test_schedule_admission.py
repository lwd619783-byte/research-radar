"""Fixed-time external clock, duplicate protection and manual recovery tests."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import schedule_admission as admission
import release_operations as operations


def external(slot='weekday-0845'):
    return {'inputs': {'trigger': 'external_schedule', 'schedule_slot': slot}}


class SlotTests(unittest.TestCase):
    def test_all_four_fixed_slots_match_native_cron(self):
        for key, (cron, hour, minute, _) in admission.SLOTS.items():
            now = dt.datetime(2026, 11, 2, hour, minute, 5, tzinfo=admission.BJ)
            with self.subTest(key=key):
                first = admission.planned_slot('workflow_dispatch', external(key), now, now)
                native = admission.planned_slot('schedule', {'schedule': cron}, now, now)
                self.assertEqual(first['plannedAt'], native['plannedAt'])
                self.assertEqual(first['slot'], native['slot'])

    def test_external_wrong_weekday_before_slot_and_delayed_queue_rejected(self):
        for created, now in (
            ('2026-11-01T08:45:00+08:00', '2026-11-01T08:45:00+08:00'),
            ('2026-11-02T08:44:59+08:00', '2026-11-02T08:45:00+08:00'),
            ('2026-11-02T11:45:01+08:00', '2026-11-02T11:45:01+08:00'),
            ('2026-11-02T08:45:01+08:00', '2026-11-02T08:45:00+08:00'),
        ):
            with self.subTest(created=created, now=now), self.assertRaises(ValueError):
                admission.planned_slot('workflow_dispatch', external(), created, now)

    def test_native_delay_keeps_its_specific_cron_slot(self):
        result = admission.planned_slot('schedule', {'schedule': '45 0 * * 1-5'},
                                       '2026-11-02T13:00:00+08:00', '2026-11-02T13:00:00+08:00')
        self.assertEqual(result['plannedAt'], '2026-11-02T08:45:00+08:00')

    def test_unknown_dispatch_and_user_timestamp_never_select_a_slot(self):
        for event in ({'inputs': {'trigger': 'external_schedule', 'schedule_slot': '../production'}},
                      {'inputs': {'trigger': 'manual', 'schedule_slot': 'weekday-0845'}},
                      {'inputs': {'trigger': 'anything'}}, {'inputs': []}):
            with self.subTest(event=event), self.assertRaises(ValueError):
                admission.trigger_kind('workflow_dispatch', event)
        event = external(); event['inputs']['plannedAt'] = '2099-01-01T08:45:00+08:00'
        result = admission.planned_slot('workflow_dispatch', event, '2026-11-02T08:45:00+08:00', '2026-11-02T08:45:00+08:00')
        self.assertEqual(result['plannedAt'], '2026-11-02T08:45:00+08:00')

    def test_successful_same_source_slot_skips_both_trigger_directions(self):
        now = '2026-11-02T09:00:00+08:00'
        manifest = {'sourceSHA': 'a' * 40, 'fixedClock': '2026-11-02T08:47:00+08:00'}
        for event_name, event in (('workflow_dispatch', external()), ('schedule', {'schedule': '45 0 * * 1-5'})):
            slot = admission.planned_slot(event_name, event, now, now)
            self.assertTrue(admission.decision(slot, manifest, {'meta': {}}, 'a' * 40, now)['skip'])
            for changed in ({**manifest, 'sourceSHA': 'b' * 40}, {**manifest, 'fixedClock': '2026-11-02T08:44:59+08:00'}):
                self.assertFalse(admission.decision(slot, changed, {'meta': {}}, 'a' * 40, now)['skip'])
            self.assertFalse(admission.decision(slot, manifest, {'meta': {}}, 'a' * 40, now, baseline_state='failed')['skip'])

    def test_manual_recovery_and_push_always_run_even_after_success(self):
        for name in ('workflow_dispatch', 'push'):
            slot = admission.planned_slot(name, {}, 'unused', 'unused')
            self.assertIsNone(slot)
            self.assertFalse(admission.decision(slot, {}, {}, 'a' * 40, 'unused')['skip'])

    def test_delayed_duplicate_succeeds_but_unserved_expired_tick_rejects(self):
        now = '2026-11-02T11:46:00+08:00'
        slot = admission.planned_slot('workflow_dispatch', external(), '2026-11-02T08:45:05+08:00', now)
        manifest = {'sourceSHA': 'a' * 40, 'fixedClock': '2026-11-02T08:47:00+08:00'}
        self.assertTrue(admission.decision(slot, manifest, {'meta': {}}, 'a' * 40, now)['skip'])
        for changed in ({**manifest, 'fixedClock': '2026-11-02T08:44:00+08:00'},
                        {**manifest, 'sourceSHA': 'b' * 40}):
            with self.assertRaisesRegex(ValueError, 'external_schedule_expired'):
                admission.decision(slot, changed, {'meta': {}}, 'a' * 40, now)

    def test_wrong_run_identity_rejected(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': admission.REPOSITORY,
               'GITHUB_REF': 'refs/heads/' + admission.SOURCE_BRANCH,
               'GITHUB_SHA': 'a' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
               'GITHUB_EVENT_NAME': 'workflow_dispatch'}
        run = {'id': 123, 'head_sha': 'a' * 40, 'head_branch': admission.SOURCE_BRANCH,
               'event': 'workflow_dispatch', 'run_attempt': 1, 'path': admission.WORKFLOW,
               'repository': {'full_name': admission.REPOSITORY}}
        admission.validate_run(env, run)
        for key, value in (('id', 124), ('head_sha', 'b' * 40), ('path', '.github/workflows/other.yml'),
                           ('run_attempt', 2), ('repository', {'full_name': 'other/repo'})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                admission.validate_run(env, {**run, key: value})

    def test_workflow_serializes_before_baseline_and_skips_every_mutation(self):
        w = json.loads((ROOT / '.github/workflows/radar-production.yml').read_text('utf-8'))
        self.assertEqual(w['concurrency'], {'group': 'radar-production', 'cancel-in-progress': False, 'queue': 'max'})
        job = w['jobs']['refresh']; steps = job['steps']; by_id = {s['id']:s for s in steps if 'id' in s}
        self.assertLess(by_id['baseline']['run'].index('release_operations.py'), by_id['baseline']['run'].index('schedule_admission.py'))
        self.assertLess(steps.index(by_id['baseline']), steps.index(by_id['collect']))
        for name in ('preflight', 'collect', 'prepare', 'publish'):
            self.assertIn("steps.baseline.outputs.skip != 'true'", by_id[name]['if'])
        self.assertEqual(by_id['result']['if'], 'always()')
        self.assertEqual(by_id['result']['env']['SCHEDULE_ADMISSION'], '${{ steps.baseline.outputs.admission }}')
        self.assertEqual(job['permissions']['actions'], 'read')

    def test_finish_records_skip_and_rejection_without_publishing_failure_notice(self):
        for admission_state, baseline, expected in (('skipped', 'success', 'skipped'),
                                                     ('denied', 'failure', 'failed'),
                                                     ('skipped', 'failure', 'failed')):
            with tempfile.TemporaryDirectory() as directory:
                env = {'GITHUB_RUN_ID':'123', 'GITHUB_SHA':'a' * 40,
                       'SCHEDULE_ADMISSION':admission_state,
                       'GITHUB_STEP_SUMMARY':str(Path(directory)/'summary.md')}
                outcomes = dict.fromkeys(('preflight','collect','prepare','publish'), 'skipped')
                outcomes['baseline'] = baseline
                with patch.dict(os.environ, env), patch.object(operations, 'failure_release') as failure, \
                        patch.object(operations, 'publish') as publish, patch.object(operations, 'wait_deployment') as wait:
                    result = operations.finish(directory, outcomes, '')
                    self.assertEqual(result['state'], expected)
                    failure.assert_not_called(); publish.assert_not_called(); wait.assert_not_called()
                self.assertEqual(json.loads((Path(directory)/'release-result.json').read_text('utf-8')), result)

    def test_document_only_push_is_excluded_but_code_still_publishes(self):
        import fnmatch
        w = json.loads((ROOT / '.github/workflows/radar-production.yml').read_text('utf-8'))
        push = w['on']['push']; self.assertNotIn('paths-ignore', push)
        def selected(path):
            result=False
            for rule in push['paths']:
                if fnmatch.fnmatchcase(path, rule.lstrip('!')):
                    result=not rule.startswith('!')
            return result
        for path in ('radar/README.md', 'radar/docs/PRODUCTION.md', 'radar/docs/nested/guide.md'):
            self.assertFalse(selected(path), path)
        for path in ('radar/scripts/build.py', 'radar/data/config.toml', '.github/workflows/radar-production.yml'):
            self.assertTrue(selected(path), path)


if __name__ == '__main__':
    unittest.main()
