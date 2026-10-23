"""Admit external clock ticks and skip already published schedule slots.

The production workflow serializes runs before this gate reads the independently
Vercel-verified baseline. No extra state branch, credential or lock is written.
Push and explicit manual recovery are never skipped by this gate. Failed
releases never consume a slot. This gate cannot guarantee GitHub queue delivery.
This module neither collects data nor publishes a release.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re

import release_operations as operations
from execution_policy import REPOSITORY, SOURCE_BRANCH

BJ = dt.timezone(dt.timedelta(hours=8))
WORKFLOW = '.github/workflows/radar-production.yml'
SLOTS = {
    'weekday-0845': ('45 0 * * 1-5', 8, 45, (0, 1, 2, 3, 4)),
    'weekday-1215': ('15 4 * * 1-5', 12, 15, (0, 1, 2, 3, 4)),
    'weekday-1815': ('15 10 * * 1-5', 18, 15, (0, 1, 2, 3, 4)),
    'monday-0650': ('50 22 * * 0', 6, 50, (0,)),
}
EXTERNAL_MAX_DELAY_MINUTES = 180


def aware(value):
    clock = dt.datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(clock, dt.datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError('schedule_clock_invalid')
    return clock.astimezone(BJ)


def trigger_kind(event_name, event):
    if event_name not in ('schedule', 'push', 'workflow_dispatch') or not isinstance(event, dict):
        raise ValueError('schedule_event_invalid')
    if event_name != 'workflow_dispatch':
        return event_name
    inputs = event.get('inputs', {})
    if not isinstance(inputs, dict):
        raise ValueError('schedule_inputs_invalid')
    trigger = inputs.get('trigger', 'manual')
    slot = inputs.get('schedule_slot', 'none')
    if trigger == 'manual' and slot in ('none', ''):
        return 'manual'
    if trigger == 'external_schedule' and slot in SLOTS:
        return 'external_schedule'
    raise ValueError('schedule_inputs_invalid')


def planned_slot(event_name, event, created_at, now):
    kind = trigger_kind(event_name, event)
    if kind in ('push', 'manual'):
        return None
    created, current = aware(created_at), aware(now)
    if created > current:
        raise ValueError('schedule_created_in_future')
    if kind == 'external_schedule':
        key = event['inputs']['schedule_slot']
        _, hour, minute, days = SLOTS[key]
        planned = created.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if created.weekday() not in days or not 0 <= (created - planned).total_seconds() <= 60 * EXTERNAL_MAX_DELAY_MINUTES:
            raise ValueError('external_schedule_outside_slot')
    else:
        matches = [key for key, spec in SLOTS.items() if spec[0] == event.get('schedule')]
        if len(matches) != 1:
            raise ValueError('schedule_cron_invalid')
        key = matches[0]
        _, hour, minute, days = SLOTS[key]
        planned = created.replace(hour=hour, minute=minute, second=0, microsecond=0)
        for _ in range(8):
            if planned <= created and planned.weekday() in days:
                break
            planned -= dt.timedelta(days=1)
        else:
            raise ValueError('schedule_slot_not_found')
    return {'kind': kind, 'slot': key, 'plannedAt': planned.isoformat(timespec='seconds')}


def verified_baseline(root):
    manifest, data = operations.verify_files(root)
    proof = json.loads((Path(root) / 'proof.json').read_text('utf-8'))
    if (proof.get('state') != 'success' or proof.get('sourceSHA') != manifest['sourceSHA']
            or proof.get('dataSHA256') != manifest['dataSHA256']):
        raise ValueError('schedule_baseline_unverified')
    operations.sha(proof.get('productionSHA'))
    state = 'current'
    if manifest['schemaVersion'] >= 2:
        state = json.loads((Path(root) / 'public/version.json').read_text('utf-8')).get('state')
    return manifest, data, state


def decision(slot, manifest, data, source_sha, now, *, baseline_state='current'):
    if slot is None:
        return {'skip': False, 'reason': 'explicit_refresh'}
    # fixedClock is bound by the verified manifest and DATA hashes. A baseline
    # built before the due time, or by other source code, cannot consume a slot.
    fixed = aware(manifest['fixedClock'])
    if fixed > aware(now):
        raise ValueError('schedule_baseline_in_future')
    already_done = (baseline_state == 'current' and manifest['sourceSHA'] == source_sha and
                    fixed >= aware(slot['plannedAt']) and
                    not any(data.get('meta', {}).get(k) for k in ('fixture', 'offline', 'reviewPreview')))
    if (not already_done and slot['kind'] == 'external_schedule' and
            (aware(now) - aware(slot['plannedAt'])).total_seconds() > 60 * EXTERNAL_MAX_DELAY_MINUTES):
        raise ValueError('external_schedule_expired')
    return dict(slot, skip=already_done, reason='slot_already_published' if already_done else 'slot_due')


def validate_run(env, run):
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != REPOSITORY
            or env.get('GITHUB_REF') != 'refs/heads/' + SOURCE_BRANCH
            or env.get('GITHUB_RUN_ATTEMPT') != '1'
            or not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', ''))
            or not re.fullmatch(r'[0-9]+', env.get('GITHUB_RUN_ID', ''))):
        raise ValueError('schedule_execution_invalid')
    if (str(run.get('id')) != env['GITHUB_RUN_ID'] or run.get('head_sha') != env['GITHUB_SHA']
            or run.get('head_branch') != SOURCE_BRANCH or run.get('path') != WORKFLOW
            or run.get('event') != env.get('GITHUB_EVENT_NAME') or run.get('run_attempt') != 1
            or (run.get('repository') or {}).get('full_name') != REPOSITORY):
        raise ValueError('schedule_run_mismatch')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        env = os.environ
        event_path = Path(env['GITHUB_EVENT_PATH'])
        if event_path.stat().st_size > 1024 * 1024:
            raise ValueError('schedule_event_too_large')
        event = json.loads(event_path.read_text('utf-8'))
        kind = trigger_kind(env.get('GITHUB_EVENT_NAME'), event)
        if kind in ('push', 'manual'):
            result = {'skip': False, 'reason': 'explicit_refresh'}
        else:
            # GitHub's immutable run creation time survives queue delays. A
            # sender-supplied timestamp is never used to decide freshness.
            run = operations.api('actions/runs/' + str(int(env['GITHUB_RUN_ID'])))
            validate_run(env, run)
            now = dt.datetime.now(BJ)
            slot = planned_slot(env['GITHUB_EVENT_NAME'], event, run['created_at'], now)
            manifest, data, state = verified_baseline(args.baseline)
            result = decision(slot, manifest, data, env['GITHUB_SHA'], now, baseline_state=state)
        print(json.dumps(result))
        with open(env['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write('skip=' + str(result['skip']).lower() + '\n')
            output.write('admission=' + ('skipped' if result['skip'] else 'allowed') + '\n')
        if env.get('GITHUB_STEP_SUMMARY'):
            message = '该计划时段已有同版本的成功发布，本次跳过重复采集与发布。' if result['skip'] else '本次刷新通过触发准入检查。'
            with open(env['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
                summary.write('### 投研雷达 · 调度准入\n' + message + '\n')
        return 0
    except Exception:
        # API errors may include transport detail. Do not echo them.
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write('admission=denied\n')
        print(json.dumps({'admitted': False, 'code': 'schedule_admission_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
