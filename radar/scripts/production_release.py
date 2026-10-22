"""Promote a fresh, same-run checked snapshot into a static Git release.

This is the explicitly authorized 2026-10-21 production path. The original
diagnostic collector and historical evidence remain unchanged.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil

import acceptance_bundle as bundle
import build
import daily_changes
import release_operations as operations

SOURCE_BRANCH = 'fix/radar-truthfulness-2026-10-18'
REPOSITORY = 'lwd619783-byte/research-radar'


def validate_release(D, receipt, now, env):
    if (env.get('GITHUB_REPOSITORY') != REPOSITORY or
            env.get('GITHUB_REF') != 'refs/heads/' + SOURCE_BRANCH or
            env.get('GITHUB_RUN_ATTEMPT') != '1' or
            env.get('GITHUB_EVENT_NAME') not in ('push', 'schedule', 'workflow_dispatch')):
        raise ValueError('production_execution_not_allowed')
    for key in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT'):
        if receipt['execution'].get(key) != env.get(key):
            raise ValueError('production_execution_mismatch')
    if not re.fullmatch('[0-9a-f]{40}', env.get('GITHUB_SHA', '')):
        raise ValueError('invalid_source_sha')
    clock = dt.datetime.fromisoformat(receipt['fixedClock'])
    if not 0 <= (now - clock).total_seconds() <= 1800:
        raise ValueError('snapshot_not_fresh_for_publication')
    if any(D['meta'].get(k) for k in ('fixture', 'offline', 'reviewPreview')):
        raise ValueError('synthetic_or_offline_publication_forbidden')
    blockers = build.release_blockers(D)
    if blockers or receipt['publication']['blockers']:
        raise ValueError('publication_blocked: ' + ','.join(blockers))
    bundle.validate_binding(D, receipt, clock)


def prepare(source, destination, now=None, env=None, baseline=None):
    source, destination = Path(source), Path(destination)
    bundle.verify_bundle(source)
    D = json.loads((source/'DATA.json').read_text('utf-8'))
    receipt = json.loads((source/'receipt.json').read_text('utf-8'))
    validate_release(D, receipt, now or dt.datetime.now(dt.UTC), env or os.environ)
    if destination.exists():
        raise ValueError('release_destination_exists')
    history = []
    if baseline is not None:
        previous_manifest, previous_data = operations.verify_files(baseline)
        proof = json.loads((Path(baseline)/'proof.json').read_text('utf-8'))
        if (proof.get('state') != 'success' or proof.get('dataSHA256') != previous_manifest['dataSHA256']
                or proof.get('sourceSHA') != previous_manifest['sourceSHA']):
            raise ValueError('baseline_proof_mismatch')
        operations.sha(proof.get('productionSHA'))
        old_history = json.loads((Path(baseline)/'history.json').read_text('utf-8'))['days'] if previous_manifest['schemaVersion'] == 2 else []
        history = daily_changes.history_with(daily_changes.project(previous_data, proof), old_history)
    run_id = receipt['execution']['GITHUB_RUN_ID']
    info = {'schemaVersion': 1, 'state': 'current', 'sourceSHA': receipt['execution']['GITHUB_SHA'],
            'runId': run_id, 'dataSHA256': bundle.data_digest(D), 'generatedAt': D['meta']['generatedAt'],
            'runUrl': f'https://github.com/{REPOSITORY}/actions/runs/{run_id}',
            'workflowUrl': operations.WORKFLOW, 'changes': daily_changes.summarize(D, history)}
    bundle.check_sensitive(info)
    public = destination/'public'
    build.render(D, public, info)
    page = public/'index.html'
    html = page.read_text('utf-8')
    old = '当前为验收版本，自动刷新与发布未启用。'
    if 'id="heroProv"' in html:
        # V3 uses one fixed disclosure in its footer instead of a preview slot.
        from output_scan import assert_output_safe
        assert_output_safe(html, D)
    else:
        if html.count(old) != 1:
            raise ValueError('production_notice_slot_mismatch')
        html = html.replace(old, '行情由定时任务更新，数据检查通过后自动发布；各字段以标注日期为准。')
    page.write_text(html, encoding='utf-8', newline='\n')
    (public/'version.json').write_bytes(bundle.encoded(info))
    (destination/'history.json').write_bytes(bundle.encoded({'schemaVersion': 1, 'days': history}))
    if bundle.embedded_data(page.read_bytes()) != D:
        raise ValueError('published_data_changed')
    config = json.loads((public/'vercel.json').read_text('utf-8'))
    (public/'vercel.json').unlink()
    config.update(buildCommand='node verify-release.cjs', outputDirectory='public',
                  installCommand='echo No dependencies', framework=None)
    (destination/'vercel.json').write_bytes(bundle.encoded(config))
    shutil.copyfile(Path(__file__).with_name('verify-release.cjs'), destination/'verify-release.cjs')
    manifest = {'schemaVersion': 2, 'sourceSHA': receipt['execution']['GITHUB_SHA'],
                'runId': receipt['execution']['GITHUB_RUN_ID'], 'fixedClock': receipt['fixedClock'],
                'priceDateRange': D['meta'].get('priceDateRange', []),
                'dataSHA256': bundle.data_digest(D), 'blockers': [],
                'historySHA256': bundle.digest((destination/'history.json').read_bytes()),
                'files': {p.name: bundle.digest(p.read_bytes()) for p in public.iterdir()}}
    bundle.check_sensitive(manifest)
    (destination/'release.json').write_bytes(bundle.encoded(manifest))
    return manifest


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--baseline', type=Path)
    args = ap.parse_args()
    print(json.dumps(prepare(args.bundle, args.out, baseline=args.baseline), ensure_ascii=False))
