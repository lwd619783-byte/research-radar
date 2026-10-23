"""Verify exact Git/Vercel releases and publish a bounded failure notice.

Only the workflow's short-lived repository token is used. No deployment bypass,
raw collection response, or credential is published. Recovery keeps DATA intact.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import acceptance_bundle as bundle

REPO = 'lwd619783-byte/research-radar'
BRANCH = 'fix/radar-truthfulness-2026-10-18'
SITE = 'https://research-radar-lkdmkl.vercel.app'
WORKFLOW = f'https://github.com/{REPO}/actions/workflows/radar-production.yml'
DEPLOY_PREFIX = 'https://vercel.com/lkdmkl/research-radar/'
SLOT = re.compile(r'(<script id="radar-operations">const OPERATIONS=)(.*?)(;</script>)', re.S)


def command(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, timeout=60)
    if p.returncode:
        raise ValueError('command_failed_' + args[0])
    return p.stdout


def api(path):
    return json.loads(command(['gh', 'api', f'repos/{REPO}/' + path]))


def sha(value):
    if not re.fullmatch('[0-9a-f]{40}', value or ''):
        raise ValueError('invalid_production_sha')
    return value


def checked_status(payload, commit):
    if payload.get('sha') != sha(commit):
        raise ValueError('deployment_sha_mismatch')
    statuses = [s for s in payload.get('statuses', []) if s.get('context') == 'Vercel']
    if not statuses:
        return {'state': 'pending', 'productionSHA': commit}
    s = max(statuses, key=lambda v: v.get('updated_at', ''))
    url = s.get('target_url', '')
    if not re.fullmatch(re.escape(DEPLOY_PREFIX) + r'[A-Za-z0-9]+', url):
        raise ValueError('unexpected_vercel_project')
    if s.get('state') not in ('pending', 'success', 'failure', 'error'):
        raise ValueError('unknown_deployment_state')
    return {'state': s['state'], 'productionSHA': commit, 'deploymentUrl': url,
            'reportedAt': s.get('updated_at')}


def status(commit):
    return checked_status(api(f'commits/{sha(commit)}/status'), commit)


def verify_files(root, allow_dry_run=False):
    root = Path(root)
    if root.is_symlink() or (root/'public').is_symlink() or (root/'release.json').is_symlink():
        raise ValueError('release_file_type')
    m = json.loads((root/'release.json').read_text('utf-8'))
    if m.get('schemaVersion') not in (1, 2, 3) or m.get('blockers') != []:
        raise ValueError('invalid_release_manifest')
    diagnostic = m.get('publicationAuthorized') is False
    if diagnostic and (not allow_dry_run or m.get('purpose') not in ('live-notion-dry-run', 'offline-rehearsal')):
        raise ValueError('diagnostic_publication_forbidden')
    if m.get('purpose') in ('live-notion-dry-run', 'offline-rehearsal') and not diagnostic:
        raise ValueError('diagnostic_authorization_invalid')
    bundle.check_sensitive(m)
    if 'scheduleAdmission' in m:
        from schedule_admission import validate_published_slot
        validate_published_slot(m['scheduleAdmission'], m)
    expected = {'index.html', 'robots.txt'} | ({'version.json'} if m['schemaVersion'] >= 2 else set())
    if set(m['files']) != expected or {p.name for p in (root/'public').iterdir()} != expected:
        raise ValueError('release_file_allowlist_mismatch')
    for name, digest in m['files'].items():
        p = root/'public'/name
        if p.is_symlink() or not p.is_file() or bundle.digest(p.read_bytes()) != digest:
            raise ValueError('release_file_hash_mismatch')
    data = bundle.embedded_data((root/'public/index.html').read_bytes())
    synthetic = any(data['meta'].get(k) for k in ('fixture', 'offline', 'reviewPreview'))
    if bundle.data_digest(data) != m['dataSHA256'] or (synthetic and not (diagnostic and m.get('purpose') == 'offline-rehearsal')):
        raise ValueError('release_data_invalid')
    if m['schemaVersion'] == 3:
        p = root/bundle.SNAPSHOT
        if p.is_symlink() or not p.is_file() or bundle.digest(p.read_bytes()) != m.get('researchSnapshotSHA256'):
            raise ValueError('research_snapshot_hash_mismatch')
        snapshot_bytes = bundle.validate_research_snapshot(json.loads(p.read_bytes()), data, m['fixedClock'])
        if snapshot_bytes != p.read_bytes() or m['researchSnapshotSHA256'] != data['meta']['notion']['snapshotSHA256']:
            raise ValueError('research_snapshot_binding_mismatch')
        if m.get('notion') != bundle.notion_summary(data):
            raise ValueError('notion_summary_mismatch')
        from release_schedule import schedule_metadata
        schedule = data['meta'].get('schedule', {})
        if not isinstance(schedule, dict) or not schedule.get('cronUtc'):
            raise ValueError('release_schedule_missing')
        expected_schedule = schedule_metadata({'cron_utc': schedule['cronUtc'],
            'late_after_minutes': schedule.get('lateAfterMinutes')}, m['fixedClock'])
        if schedule != expected_schedule:
            raise ValueError('release_schedule_mismatch')
        from output_scan import assert_output_safe
        assert_output_safe((root/'public/index.html').read_text('utf-8'), data)
    elif 'notion' in data.get('meta', {}):
        raise ValueError('notion_release_requires_v3')
    if m['schemaVersion'] >= 2:
        if (root/'history.json').is_symlink() or not (root/'history.json').is_file():
            raise ValueError('release_file_type')
        if bundle.digest((root/'history.json').read_bytes()) != m['historySHA256']:
            raise ValueError('history_hash_mismatch')
        history = json.loads((root/'history.json').read_text('utf-8'))
        if history.get('schemaVersion') != 1 or len(history['days']) > 8:
            raise ValueError('history_invalid')
        ops = json.loads(SLOT.search((root/'public/index.html').read_text('utf-8')).group(2))
        version = json.loads((root/'public/version.json').read_text('utf-8'))
        bundle.check_sensitive(history)
        bundle.check_sensitive(version)
        if ops != version or ops.get('dataSHA256') != m['dataSHA256'] or ops.get('sourceSHA') != m['sourceSHA']:
            raise ValueError('release_status_binding_mismatch')
        if 'scheduleAdmission' in m:
            from schedule_admission import publication_schedule
            expected_schedule = publication_schedule(m, data)
            if expected_schedule is None and 'schedule' in version:
                raise ValueError('publication_schedule_without_data_schedule')
            if version.get('schedule') != expected_schedule:
                raise ValueError('publication_schedule_mismatch')
        elif 'schedule' in version:
            raise ValueError('publication_schedule_without_ownership')
    return m, data


def fetch_baseline(destination):
    destination = Path(destination)
    commits = api('commits?sha=production&per_page=12')
    for c in commits:
        commit = sha(c['sha'])
        proof = status(commit)
        if proof['state'] != 'success':
            continue
        # Checkout fetched every branch without retained credentials. Read exact
        # objects, never executable code from the production branch.
        manifest = json.loads(command(['git', 'show', commit + ':release.json']))
        names = ['release.json', 'vercel.json', 'verify-release.cjs', 'public/index.html', 'public/robots.txt']
        if manifest.get('schemaVersion', 0) >= 2:
            names += ['public/version.json', 'history.json']
        if manifest.get('schemaVersion') == 3:
            names += [bundle.SNAPSHOT]
        destination.mkdir(parents=True, exist_ok=False)
        for name in names:
            p = destination/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(command(['git', 'show', commit + ':' + name]))
        m, _ = verify_files(destination)
        proof.update(sourceSHA=m['sourceSHA'], dataSHA256=m['dataSHA256'])
        (destination/'proof.json').write_bytes(bundle.encoded(proof))
        return proof
    raise ValueError('no_verified_production_baseline')


def refresh_hashes(root):
    root = Path(root)
    m = json.loads((root/'release.json').read_text('utf-8'))
    m['files'] = {p.name: bundle.digest(p.read_bytes()) for p in (root/'public').iterdir()}
    (root/'release.json').write_bytes(bundle.encoded(m))


def failure_release(baseline, destination, stage, run_id, source_sha):
    m, data = verify_files(baseline)
    if m['schemaVersion'] < 2:
        raise ValueError('baseline_has_no_failure_notice_slot')
    if stage not in ('preflight', 'baseline', 'collect', 'prepare', 'publish', 'deployment'):
        raise ValueError('invalid_failure_stage')
    if not re.fullmatch(r'\d+', run_id):
        raise ValueError('invalid_run_id')
    sha(source_sha)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('release_destination_exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.radar-recovery-', dir=destination.parent) as temporary:
        output = Path(temporary)/'release'
        _failure_materialize(baseline, output, stage, run_id, source_sha, data)
        bundle.atomic_directory_rename(output, destination)


def _failure_materialize(baseline, destination, stage, run_id, source_sha, data):
    shutil.copytree(baseline, destination, ignore=shutil.ignore_patterns('proof.json'))
    page = destination/'public/index.html'
    text = page.read_text('utf-8')
    ops = json.loads(SLOT.search(text).group(2))
    ops.update(state='failed', failedStage=stage, attemptedAt=dt.datetime.now(dt.UTC).isoformat(),
               attemptedSourceSHA=source_sha, attemptRunId=run_id,
               runUrl=f'https://github.com/{REPO}/actions/runs/{run_id}')
    # generatedAt, dataSHA256, daily summary, research flags all stay unchanged.
    write_operations(destination, data, ops)
    refresh_hashes(destination)
    _, result = verify_files(destination)
    if result != data:
        raise ValueError('failure_recovery_changed_data')


def write_operations(destination, data, ops):
    """Update the bounded operations slots without changing embedded DATA."""
    destination = Path(destination)
    page = destination/'public/index.html'
    text = page.read_text('utf-8')
    encoded = json.dumps(ops, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    for char, escaped in (('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'), ('\u2028', '\\u2028'), ('\u2029', '\\u2029')):
        encoded = encoded.replace(char, escaped)
    text, count = SLOT.subn(lambda x: x[1] + encoded + x[3], text)
    if count != 1:
        raise ValueError('failure_notice_slot_mismatch')
    if 'id="heroProv"' in text:
        from render_v3 import date, render_pulse
        fragment = render_pulse(data, date(data['meta'].get('today')), ops)
        pulse = re.compile(r'(<div\b(?=[^>]*\bid="pulse")[^>]*>)(.*?)(</div>)', re.S)
        def replace_pulse(match):
            state = ' bad' if ops.get('state') == 'failed' else ''
            opening = re.sub(r'class="[^"]*"', 'class="pulse' + state + '"', match[1])
            return opening + fragment + match[3]
        text, count = pulse.subn(replace_pulse, text)
        if count != 1:
            raise ValueError('failure_pulse_slot_mismatch')
    page.write_text(text, encoding='utf-8', newline='\n')
    (destination/'public/version.json').write_bytes(bundle.encoded(ops))
    if bundle.embedded_data(page.read_bytes()) != data:
        raise ValueError('operations_changed_data')


def prevent_publication_regression(candidate, data, current, current_data):
    """Compare verified bytes from the freshly fetched production HEAD.

    Queue order is not dispatch order. A non-force push protects the remaining
    fetch-to-push race; these comparisons protect against an already newer HEAD.
    Legacy releases without fixedClock still have the hash-bound generatedAt.
    """
    from schedule_admission import aware, validate_published_slot
    for manifest, payload in ((candidate, data), (current, current_data)):
        aware(payload['meta']['generatedAt'])
        aware(manifest.get('fixedClock', payload['meta']['generatedAt']))
    new_clock = aware(candidate.get('fixedClock', data['meta']['generatedAt']))
    old_clock = aware(current.get('fixedClock', current_data['meta']['generatedAt']))
    if (new_clock < old_clock or
            aware(data['meta']['generatedAt']) < aware(current_data['meta']['generatedAt'])):
        raise ValueError('publication_older_than_production')
    if new_clock == old_clock and candidate['dataSHA256'] != current['dataSHA256']:
        raise ValueError('publication_same_clock_different_data')
    if 'scheduleAdmission' in candidate and 'scheduleAdmission' in current:
        incoming = validate_published_slot(candidate['scheduleAdmission'], candidate)
        previous = validate_published_slot(current['scheduleAdmission'], current)
        if aware(incoming['plannedAt']) < aware(previous['plannedAt']):
            raise ValueError('publication_older_schedule_slot')


def publish(root):
    if (os.environ.get('GITHUB_REPOSITORY') != REPO or os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH
            or os.environ.get('GITHUB_RUN_ATTEMPT') != '1'
            or os.environ.get('GITHUB_EVENT_NAME') not in ('push', 'schedule', 'workflow_dispatch')):
        raise ValueError('publication_execution_not_allowed')
    manifest, data = verify_files(root)
    source = sha(os.environ.get('GITHUB_SHA'))
    if command(['git', 'rev-parse', 'HEAD']).decode().strip() != source:
        raise ValueError('publication_source_mismatch')
    if api('git/ref/heads/' + BRANCH)['object']['sha'] != source:
        raise ValueError('source_advanced_skip_obsolete_release')
    version = json.loads((Path(root)/'public/version.json').read_text('utf-8'))
    recovery = version.get('state') == 'failed'
    if not recovery:
        if manifest['sourceSHA'] != source or manifest['runId'] != os.environ.get('GITHUB_RUN_ID'):
            raise ValueError('publication_run_mismatch')
        # Do not trust an admission clock supplied in env or in a candidate.
        # GitHub provides the event file; API identity and created_at survive
        # concurrency waits, unlike run_started_at or the collection clock.
        from schedule_admission import publication_slot
        event_path = Path(os.environ['GITHUB_EVENT_PATH'])
        if event_path.stat().st_size > 1024 * 1024:
            raise ValueError('schedule_event_too_large')
        event = json.loads(event_path.read_text('utf-8'))
        recorded = publication_slot(os.environ, api('actions/runs/' + os.environ['GITHUB_RUN_ID']),
                                    event, manifest['fixedClock'])
        if 'scheduleAdmission' in manifest and manifest['scheduleAdmission'] != recorded:
            raise ValueError('publication_schedule_mismatch')
        manifest = dict(manifest)
        if recorded is not None:
            manifest['scheduleAdmission'] = recorded
    command(['gh', 'auth', 'setup-git'])
    work = Path(os.environ['RUNNER_TEMP']) / ('publish-' + Path(root).name)
    command(['git', 'init', '-q', '-b', 'production', str(work)])
    command(['git', 'remote', 'add', 'origin', f'https://github.com/{REPO}.git'], work)
    command(['git', 'fetch', '-q', '--depth=1', 'origin', 'production'], work)
    command(['git', 'reset', '-q', '--hard', 'FETCH_HEAD'], work)
    current, current_data = verify_files(work)
    prevent_publication_regression(manifest, data, current, current_data)
    if recovery and (manifest['dataSHA256'] != current['dataSHA256'] or
                     manifest.get('fixedClock') != current.get('fixedClock')):
        raise ValueError('recovery_baseline_is_no_longer_current')
    names = ['public/index.html', 'public/robots.txt', 'public/version.json', 'release.json',
             'history.json', 'vercel.json', 'verify-release.cjs']
    if manifest['schemaVersion'] == 3:
        names.append(bundle.SNAPSHOT)
    else:
        # A TOML rollback has no usable Notion baseline, including on disk.
        command(['git', 'rm', '-q', '--ignore-unmatch', '--', bundle.SNAPSHOT], work)
    for name in names:
        dest = work/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(root)/name, dest)
    (work/'release.json').write_bytes(bundle.encoded(manifest))
    if 'scheduleAdmission' in manifest:
        from schedule_admission import publication_schedule
        schedule = publication_schedule(manifest, data)
        if schedule is not None:
            version['schedule'] = schedule
            write_operations(work, data, version)
            refresh_hashes(work)
    verify_files(work)
    command(['git', 'config', 'user.name', 'github-actions[bot]'], work)
    command(['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'], work)
    command(['git', 'add', '--', *names], work)
    command(['git', 'commit', '-q', '-m', f'Publish radar from {source} (run {os.environ["GITHUB_RUN_ID"]})'], work)
    commit = command(['git', 'rev-parse', 'HEAD'], work).decode().strip()
    command(['git', 'push', 'origin', 'HEAD:refs/heads/production'], work)
    return sha(commit)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def protection_check():
    results = []
    opener = urllib.request.build_opener(NoRedirect())
    for path in ('/', '/version.json'):
        try:
            with opener.open(urllib.request.Request(SITE + path, method='GET'), timeout=20) as r:
                code, location = r.status, r.headers.get('Location', '')
        except urllib.error.HTTPError as exc:
            code, location = exc.code, exc.headers.get('Location', '')
        host = urllib.parse.urlsplit(location).hostname
        protected = code in (401, 403) or (code in (302, 303, 307, 308) and host in ('vercel.com', 'vercel.app'))
        if not protected:
            raise ValueError('anonymous_login_protection_not_confirmed')
        results.append({'path': path, 'status': code, 'protected': True})
    return results


def wait_deployment(commit, timeout=300):
    deadline = time.monotonic() + timeout
    while True:
        result = status(commit)
        if result['state'] == 'success':
            result['protection'] = protection_check()
            result['checkedAt'] = dt.datetime.now(dt.UTC).isoformat()
            result['domainContentCheck'] = 'authenticated_browser_version_check'
            return result
        if result['state'] in ('failure', 'error'):
            raise ValueError('vercel_deployment_failed')
        if time.monotonic() >= deadline:
            raise ValueError('vercel_deployment_timeout')
        time.sleep(10)


def finish(temp, outcomes, production_sha):
    temp = Path(temp)
    admission = os.environ.get('SCHEDULE_ADMISSION', '')
    if admission and admission != 'allowed':
        # Always account for skipped/rejected ticks, but never deploy a failure
        # notice for a slot that did not attempt collection or publication.
        safe_skip = (admission == 'skipped' and outcomes.get('baseline') == 'success'
                     and not production_sha and all(outcomes.get(k) == 'skipped'
                         for k in ('preflight', 'collect', 'prepare', 'publish')))
        result = {'runId': os.environ['GITHUB_RUN_ID'], 'sourceSHA': os.environ['GITHUB_SHA'],
                  'stages': outcomes, 'state': 'skipped' if safe_skip else 'failed',
                  'reason': 'slot_already_published' if safe_skip else 'schedule_admission_failed'}
        bundle.check_sensitive(result)
        (temp/'release-result.json').write_bytes(bundle.encoded(result))
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write('## 投研雷达发布结果\n\n' +
                          ('该时段已有同版本成功发布，本次跳过重复刷新。' if safe_skip else
                           '调度准入未通过，本次没有采集或发布；检查时段与安全诊断。') + '\n')
        return result
    failed = next((k for k in ('preflight', 'baseline', 'collect', 'prepare', 'publish')
                   if outcomes.get(k) != 'success'), None)
    result = {'runId': os.environ['GITHUB_RUN_ID'], 'sourceSHA': os.environ['GITHUB_SHA'],
              'stages': outcomes, 'state': 'failed' if failed else 'pending'}
    if not failed:
        try:
            result['deployment'] = wait_deployment(production_sha)
            result['state'] = 'success'
        except Exception as exc:
            failed = 'deployment'
            result.update(state='failed', reason=type(exc).__name__ + ':' + str(exc)[:100])
    if failed:
        result['failedStage'] = failed
        try:
            recovery = temp/'radar-recovery'
            failure_release(temp/'radar-baseline', recovery, failed, os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_SHA'])
            result['recovery'] = wait_deployment(publish(recovery), timeout=180)
        except Exception as exc:
            result['recovery'] = {'state': 'unavailable', 'reason': type(exc).__name__ + ':' + str(exc)[:100]}
        print(f'::error title=投研雷达更新失败::{failed} 阶段未通过；保留已核实快照，详见运行摘要与诊断附件。')
    bundle.check_sensitive(result)
    (temp/'release-result.json').write_bytes(bundle.encoded(result))
    summary = Path(os.environ['GITHUB_STEP_SUMMARY'])
    with summary.open('a', encoding='utf-8') as f:
        f.write('## 投研雷达发布结果\n\n' + ('已核对 Vercel 对应提交上线回执和匿名登录保护。' if not failed else
                f'更新失败：{failed}。未将失败采集当作新数据；失败提示发布结果见附件。') + '\n\n')
        f.write(f'源码 `{result["sourceSHA"]}`\n\n')
        if not failed:
            f.write(f'生产 `{production_sha}` · [Vercel 回执]({result["deployment"]["deploymentUrl"]})\n\n')
        f.write(f'[受保护的线上页面]({SITE}) · 登录后页面会核对同源版本并提示新版。\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('baseline', 'publish', 'finish'))
    p.add_argument('--path', type=Path, required=True)
    p.add_argument('--sha', default='')
    p.add_argument('--outcomes')
    args = p.parse_args()
    if args.action == 'baseline':
        print(json.dumps(fetch_baseline(args.path)))
    elif args.action == 'publish':
        commit = publish(args.path)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'production_sha={commit}\n')
        print(json.dumps({'productionSHA': commit}))
    else:
        outcomes = (json.loads(args.outcomes) if args.outcomes else
                    {k: v['outcome'] for k, v in json.loads(os.environ['STAGE_OUTCOMES']).items()})
        result = finish(args.path, outcomes, args.sha)
        print(json.dumps(result))
        raise SystemExit(0 if result['state'] in ('success', 'skipped') else 1)
