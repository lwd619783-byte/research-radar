"""Queued schedules keep their real slot; late releases cannot roll back HEAD.

All records are independent synthetic test data. Publication tests use the real
release-file verifier and only replace Git/GitHub transport, never the gates.
"""
import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import acceptance_bundle as bundle
import release_operations as operations
import schedule_admission as admission

SOURCE = 'a' * 40
DAY = '2026-11-02'


def clock(time, day=DAY):
    return day + 'T' + time + ':00+08:00'


def environment(event='schedule', run_id='456'):
    return {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': operations.REPO,
            'GITHUB_REF': 'refs/heads/' + operations.BRANCH, 'GITHUB_SHA': SOURCE,
            'GITHUB_RUN_ID': run_id, 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_EVENT_NAME': event}


def run(env=None, created=None, started=None):
    env = env or environment()
    return {'id': int(env['GITHUB_RUN_ID']), 'head_sha': env['GITHUB_SHA'],
            'head_branch': operations.BRANCH, 'event': env['GITHUB_EVENT_NAME'],
            'run_attempt': 1, 'path': admission.WORKFLOW,
            'repository': {'full_name': operations.REPO},
            'created_at': created or clock('08:46'), 'run_started_at': started or clock('13:00')}


def event(slot='weekday-0845', external=False):
    return ({'inputs': {'trigger': 'external_schedule', 'schedule_slot': slot}}
            if external else {'schedule': admission.SLOTS[slot][0]})


def ownership(time='13:00', slot='weekday-0845', run_id='456', created='08:46'):
    env = environment(run_id=run_id)
    return admission.publication_slot(env, run(env, clock(created)), event(slot), clock(time))


def make_release(root, time='13:00', run_id='456', source=SOURCE, *, recorded=None,
                 generated=None, price=10):
    root.mkdir(); (root/'public').mkdir()
    data = {'meta': {'generatedAt': generated or clock(time)}, 'companies': [
        {'id': 'TEST', 'sym': 'TEST', 'price': price, 'pricePhase': 'unknown',
         'ld': DAY, 'next': None, 'research': {'status': 'unverified'}}]}
    info = {'schemaVersion': 1, 'state': 'current', 'sourceSHA': source, 'runId': run_id,
            'dataSHA256': bundle.data_digest(data), 'generatedAt': data['meta']['generatedAt']}
    page = ('<script>const DATA=' + json.dumps(data) + ';</script>\n'
            '<script id="radar-operations">const OPERATIONS=' + json.dumps(info) + ';</script>')
    (root/'public/index.html').write_text(page, encoding='utf-8')
    (root/'public/robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
    (root/'public/version.json').write_bytes(bundle.encoded(info))
    (root/'history.json').write_bytes(bundle.encoded({'schemaVersion': 1, 'days': []}))
    (root/'vercel.json').write_bytes(bundle.encoded({'buildCommand': 'node verify-release.cjs'}))
    shutil.copyfile(ROOT/'radar/scripts/verify-release.cjs', root/'verify-release.cjs')
    manifest = {'schemaVersion': 2, 'sourceSHA': source, 'runId': run_id, 'fixedClock': clock(time),
                'dataSHA256': bundle.data_digest(data), 'blockers': [], 'files': {},
                'historySHA256': bundle.digest((root/'history.json').read_bytes())}
    if recorded is not None:
        manifest['scheduleAdmission'] = recorded
    (root/'release.json').write_bytes(bundle.encoded(manifest))
    operations.refresh_hashes(root)
    return operations.verify_files(root)


class SlotOwnershipTests(unittest.TestCase):
    def test_queue_start_after_next_slot_does_not_change_github_created_slot(self):
        env = environment()
        value = admission.publication_slot(env, run(env), event(), clock('13:00'))
        self.assertEqual(value['plannedAt'], clock('08:45'))
        self.assertEqual(value['createdAt'], clock('08:46'))
        self.assertEqual(value['runId'], '456')

    def test_all_four_slots_survive_an_overnight_queue(self):
        for slot, (_, hour, minute, _) in admission.SLOTS.items():
            created = clock(f'{hour:02}:{minute:02}')
            value = admission.publication_slot(environment(), run(created=created,
                started=clock('19:00', '2026-11-03')), event(slot), clock('19:00', '2026-11-03'))
            self.assertEqual(value['plannedAt'], created, slot)

    def test_sender_or_environment_clock_cannot_move_slot(self):
        env = environment() | {'SCHEDULE_PLANNED_AT': clock('18:15'), 'SCHEDULE_SLOT': 'weekday-1815'}
        payload = event() | {'plannedAt': clock('18:15'), 'created_at': clock('18:16')}
        result = admission.publication_slot(env, run(env), payload, clock('19:00'))
        self.assertEqual(result['plannedAt'], clock('08:45'))

    def test_delayed_morning_release_does_not_consume_noon_or_evening(self):
        manifest = {'sourceSHA': SOURCE, 'runId': '456', 'fixedClock': clock('13:00'),
                    'scheduleAdmission': ownership()}
        for key, skip in (('weekday-0845', True), ('weekday-1215', False), ('weekday-1815', False)):
            slot = admission.planned_slot('schedule', event(key), clock('19:00'), clock('19:00'))
            result = admission.decision(slot, manifest, {'meta': {}}, SOURCE, clock('19:00'))
            self.assertEqual(result['skip'], skip, key)

    def test_newer_success_consumes_old_slot_but_failed_or_other_source_does_not(self):
        manifest = {'sourceSHA': SOURCE, 'runId': '456', 'fixedClock': clock('13:00'),
                    'scheduleAdmission': ownership(slot='weekday-1215', created='12:16')}
        slot = admission.planned_slot('schedule', event(), clock('08:46'), clock('13:00'))
        self.assertTrue(admission.decision(slot, manifest, {'meta': {}}, SOURCE, clock('13:00'))['skip'])
        self.assertFalse(admission.decision(slot, manifest, {'meta': {}}, SOURCE, clock('13:00'), baseline_state='failed')['skip'])
        self.assertFalse(admission.decision(slot, manifest, {'meta': {}}, 'b' * 40, clock('13:00'))['skip'])

    def test_external_queue_expires_without_claiming_a_different_slot(self):
        env = environment('workflow_dispatch')
        slot = admission.publication_slot(env, run(env), event(external=True), clock('13:00'))
        self.assertEqual(slot['plannedAt'], clock('08:45'))
        manifest = {'sourceSHA': SOURCE, 'fixedClock': clock('08:30')}
        with self.assertRaisesRegex(ValueError, 'external_schedule_expired'):
            admission.decision(slot, manifest, {'meta': {}}, SOURCE, clock('13:00'))

    def test_unknown_or_mismatched_persisted_attribution_is_rejected(self):
        manifest = {'sourceSHA': SOURCE, 'runId': '456', 'fixedClock': clock('13:00')}
        for field, value in (('slot', 'weekday-1215'), ('plannedAt', clock('12:15')),
                             ('createdAt', clock('14:00')), ('runId', '999'),
                             ('sourceSHA', 'b' * 40), ('slot', []), ('extra', 'untrusted')):
            bad = ownership(); bad[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                admission.validate_published_slot(bad, manifest)

    def test_verified_baseline_rechecks_persisted_created_at_against_github(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'baseline'
            manifest, _ = make_release(root, recorded=ownership())
            (root/'proof.json').write_bytes(bundle.encoded({'state': 'success',
                'productionSHA': 'c' * 40, 'sourceSHA': SOURCE, 'dataSHA256': manifest['dataSHA256']}))
            with patch.object(operations, 'api', return_value=run()) as api:
                self.assertEqual(admission.verified_baseline(root)[2], 'current')
                api.assert_called_once_with('actions/runs/456')
            for mutation in ({'created_at': clock('08:47')}, {'head_sha': 'b' * 40}, {'id': 999}):
                with patch.object(operations, 'api', return_value=run() | mutation), self.assertRaises(ValueError):
                    admission.verified_baseline(root)

    def test_legacy_unattributed_release_remains_backward_compatible(self):
        slot = admission.planned_slot('schedule', event('weekday-1215'), clock('13:00'), clock('13:00'))
        self.assertTrue(admission.decision(slot, {'sourceSHA': SOURCE, 'fixedClock': clock('13:00')},
                                          {'meta': {}}, SOURCE, clock('13:00'))['skip'])

    def test_real_admission_cli_does_not_skip_noon_after_late_morning_publish(self):
        class FixedClock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.fromisoformat(clock('13:00')).astimezone(tz)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'baseline'
            manifest, _ = make_release(root, run_id='123', recorded=ownership(run_id='123'))
            (root/'proof.json').write_bytes(bundle.encoded({'state': 'success',
                'productionSHA': 'c' * 40, 'sourceSHA': SOURCE, 'dataSHA256': manifest['dataSHA256']}))
            event_path, output = Path(temp)/'event.json', Path(temp)/'output'
            event_path.write_bytes(bundle.encoded(event('weekday-1215')))
            env = environment() | {'GITHUB_EVENT_PATH': str(event_path), 'GITHUB_OUTPUT': str(output)}
            runs = {'actions/runs/456': run(created=clock('12:16')),
                    'actions/runs/123': run(environment(run_id='123'))}
            with patch.dict(os.environ, env, clear=True), patch.object(operations, 'api', side_effect=runs.__getitem__), \
                    patch.object(admission.dt, 'datetime', FixedClock), contextlib.redirect_stdout(io.StringIO()) as log:
                self.assertEqual(admission.main(['--baseline', str(root)]), 0)
            self.assertIn('skip=false\nadmission=allowed\n', output.read_text())
            self.assertEqual(json.loads(log.getvalue())['plannedAt'], clock('12:15'))


class PublishOrderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.candidate, self.current = self.base/'candidate', self.base/'production'
        self.env = environment() | {'RUNNER_TEMP': str(self.base), 'GITHUB_EVENT_PATH': str(self.base/'event.json')}
        (self.base/'event.json').write_bytes(bundle.encoded(event()))
        self.calls = []
        self.api_run = run()
        self.remote_source = SOURCE

    def transport(self, args, cwd=None):
        self.calls.append(list(args))
        if args[:3] == ['git', 'rev-parse', 'HEAD']:
            return (SOURCE if cwd is None else 'd' * 40).encode()
        if args[:2] == ['git', 'init']:
            Path(args[-1]).mkdir()
        if args[:2] == ['git', 'reset']:
            shutil.copytree(self.current, cwd, dirs_exist_ok=True)
        return b''

    def api(self, path):
        if path == 'git/ref/heads/' + operations.BRANCH:
            return {'object': {'sha': self.remote_source}}
        if path == 'actions/runs/456':
            return self.api_run
        raise AssertionError('unexpected API path: ' + path)

    def publish(self, root=None):
        with patch.dict(os.environ, self.env, clear=True), patch.object(operations, 'api', side_effect=self.api), \
                patch.object(operations, 'command', side_effect=self.transport):
            return operations.publish(root or self.candidate)

    def assert_no_commit_or_push(self):
        self.assertFalse(any(args[:2] in (['git', 'commit'], ['git', 'push']) for args in self.calls))

    def test_real_publish_writes_verified_original_slot_and_not_sender_attribution(self):
        make_release(self.current, '08:30', '123')
        original, data = make_release(self.candidate)
        self.env['SCHEDULE_PLANNED_AT'] = clock('18:15')
        self.assertEqual(self.publish(), 'd' * 40)
        published, actual = operations.verify_files(self.base/'publish-candidate')
        self.assertEqual(actual, data)
        self.assertEqual(published['scheduleAdmission']['plannedAt'], clock('08:45'))
        self.assertEqual(published['scheduleAdmission']['createdAt'], clock('08:46'))
        self.assertEqual(published['scheduleAdmission']['runId'], original['runId'])
        self.assertEqual(json.loads((self.candidate/'release.json').read_text()), original)
        self.assertIn(['git', 'push', 'origin', 'HEAD:refs/heads/production'], self.calls)
        self.assertFalse(any('--force' in argument for args in self.calls for argument in args))

    def test_freshly_fetched_newer_production_blocks_late_older_bundle(self):
        make_release(self.current, '13:10', '789')
        make_release(self.candidate, '13:00')
        before = (self.current/'public/index.html').read_bytes()
        with self.assertRaisesRegex(ValueError, 'publication_older_than_production'):
            self.publish()
        self.assert_no_commit_or_push()
        self.assertEqual((self.base/'publish-candidate/public/index.html').read_bytes(), before)

    def test_new_collection_clock_cannot_hide_regressed_data_generated_at(self):
        make_release(self.current, '13:00', '789')
        make_release(self.candidate, '13:10', generated=clock('12:59'))
        with self.assertRaisesRegex(ValueError, 'publication_older_than_production'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_equal_clock_with_different_data_is_a_conflict_not_newer(self):
        make_release(self.current, '13:00', '789', price=11)
        make_release(self.candidate, '13:00', price=10)
        with self.assertRaisesRegex(ValueError, 'publication_same_clock_different_data'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_late_morning_cannot_replace_already_published_noon_slot(self):
        make_release(self.current, '12:30', '789', recorded=ownership(
            '12:30', 'weekday-1215', '789', '12:16'))
        make_release(self.candidate, '13:00')
        with self.assertRaisesRegex(ValueError, 'publication_older_schedule_slot'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_current_source_check_still_prevents_obsolete_code_publish(self):
        make_release(self.current, '08:30', '123'); make_release(self.candidate)
        self.remote_source = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'source_advanced_skip_obsolete_release'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_candidate_run_binding_and_api_identity_are_both_required(self):
        make_release(self.current, '08:30', '123'); make_release(self.candidate)
        self.api_run['head_sha'] = 'b' * 40
        with self.assertRaisesRegex(ValueError, 'schedule_run_mismatch'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_publication_rejects_candidate_from_different_run(self):
        make_release(self.current, '08:30', '123'); make_release(self.candidate, run_id='999')
        with self.assertRaisesRegex(ValueError, 'publication_run_mismatch'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_nonforce_push_race_fails_without_overwriting_or_retrying(self):
        make_release(self.current, '08:30', '123'); make_release(self.candidate)
        base_transport = self.transport
        def advanced_production(args, cwd=None):
            result = base_transport(args, cwd)
            if args[:2] == ['git', 'push']:
                raise ValueError('command_failed_git')
            return result
        self.transport = advanced_production
        with self.assertRaisesRegex(ValueError, 'command_failed_git'):
            self.publish()
        pushes = [args for args in self.calls if args[:2] == ['git', 'push']]
        self.assertEqual(pushes, [['git', 'push', 'origin', 'HEAD:refs/heads/production']])

    def test_failure_notice_preserves_original_slot_and_never_claims_failed_attempt(self):
        make_release(self.current, '13:00', '123', recorded=ownership(run_id='123'))
        recovery = self.base/'recovery'
        operations.failure_release(self.current, recovery, 'collect', '456', SOURCE)
        self.assertEqual(self.publish(recovery), 'd' * 40)
        manifest, _ = operations.verify_files(self.base/'publish-recovery')
        version = json.loads((self.base/'publish-recovery/public/version.json').read_text())
        self.assertEqual(version['state'], 'failed')
        self.assertEqual(manifest['scheduleAdmission']['runId'], '123')
        self.assertEqual(version['attemptRunId'], '456')

    def test_failure_from_old_baseline_cannot_overwrite_new_production(self):
        old = self.base/'old-baseline'
        make_release(old, '08:30', '123')
        operations.failure_release(old, self.candidate, 'collect', '456', SOURCE)
        make_release(self.current, '13:00', '789')
        with self.assertRaisesRegex(ValueError, 'publication_older_than_production'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_legacy_current_manifest_without_fixed_clock_uses_bound_data_clock(self):
        make_release(self.current, '13:10', '789'); make_release(self.candidate)
        manifest = json.loads((self.current/'release.json').read_text())
        del manifest['fixedClock']
        (self.current/'release.json').write_bytes(bundle.encoded(manifest))
        with self.assertRaisesRegex(ValueError, 'publication_older_than_production'):
            self.publish()
        self.assert_no_commit_or_push()

    def test_optional_slot_manifest_passes_both_python_and_node_verifiers(self):
        make_release(self.candidate, recorded=ownership())
        operations.verify_files(self.candidate)
        process = subprocess.run(['node', str(ROOT/'radar/scripts/verify-release.cjs')],
            cwd=self.candidate, env=os.environ | {'VERCEL_ENV': 'production',
                'VERCEL_GIT_COMMIT_REF': 'production', 'VERCEL_GIT_COMMIT_SHA': 'c' * 40},
            capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)


if __name__ == '__main__':
    unittest.main()
