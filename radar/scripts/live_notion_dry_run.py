"""Verify a real manual Notion dry-run and export only safe review diagnostics."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import acceptance_bundle as bundle
import production_collect as collector
import production_release as release
from research_snapshot import canonical_json


class DryRunError(ValueError):
    pass


def classify(data=None, diagnostics=None):
    codes = [(diagnostics or {}).get('code')]
    codes += [note.get('code') for note in (diagnostics or {}).get('notionErrors', [])]
    fallback = (data or {}).get('meta', {}).get('notion', {}).get('fallbackTables', [])
    codes += [note.get('code') for note in fallback]
    for code, step in (('notion_token_missing', '附录 A 第 1–4、6 步'),
                       ('notion_unauthorized', '附录 A 第 6 步（重新填写正确 token）'),
                       ('notion_not_found', '附录 A 第 4 步（把 connection 添加到数据后台页面）'),
                       ('notion_forbidden', '附录 A 第 2 步（勾选 Read content）')):
        if code in codes:
            return {'ready': False, 'code': code, 'action': step}
    if data is None:
        return {'ready': False, 'code': 'live_collection_failed', 'action': '检查安全诊断与行情来源状态'}
    if fallback:
        return {'ready': False, 'code': 'live_notion_fallback', 'action': '修复表读取后重新演练'}
    if data['meta'].get('weekly', {}).get('mode') != 'ai':
        return {'ready': False, 'code': 'weekly_refresh_required',
                'action': '请让 ChatGPT 按《维护规则》第五节做第一次完整刷新'}
    return {'ready': True, 'code': 'live_notion_ready', 'action': '无'}


def export_artifact(destination, *, data=None, snapshot=None, summary, result, diagnostics=None):
    """Atomic explicit allowlist. This archive contains no deployable website."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise DryRunError('artifact_destination_exists')
    values = {'result.json': result}
    if data is not None:
        for key in ('notion', 'weekly', 'daily'):
            values[f'meta.{key}.json'] = data['meta'].get(key, {})
    if snapshot is not None:
        values['research-snapshot.json'] = snapshot
    if diagnostics:
        values['diagnostic.json'] = diagnostics
    payload = {name: canonical_json(value).encode('utf-8') for name, value in values.items()}
    payload['step-summary.md'] = summary.encode('utf-8')
    for value in [*values.values(), summary]:
        bundle.check_sensitive(value)
    if sum(map(len, payload.values())) > bundle.MAX_BUNDLE:
        raise DryRunError('artifact_size_limit')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.live-notion-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'artifact'; stage.mkdir()
        for name, content in payload.items():
            (stage / name).write_bytes(content)
        bundle.atomic_directory_rename(stage, destination)
    return sorted(payload)


def verify(*, source, destination, artifact, baseline=None, work=None, env=None,
           now=None, node=None):
    env = env if env is not None else os.environ
    if 'NOTION_TOKEN' in env:
        raise DryRunError('unexpected_secret_scope')
    collector.admit(env, live_dry_run=True)
    source, destination, artifact = Path(source), Path(destination), Path(artifact)
    diagnostics = {}
    if work and (Path(work) / 'diagnostic.json').is_file():
        diagnostics = json.loads((Path(work) / 'diagnostic.json').read_text('utf-8'))
        bundle.check_sensitive(diagnostics)
    data, snapshot = None, None
    if (source / 'DATA.json').is_file():
        # verify_bundle checks the complete allowlist and byte bindings before
        # any data from a collection run is considered for release verification.
        bundle.verify_bundle(source)
        data = json.loads((source / 'DATA.json').read_text('utf-8'))
        snapshot = json.loads((source / 'research-snapshot.json').read_text('utf-8'))
    state = classify(data, diagnostics)
    verified = False
    code = None
    if data is not None:
        try:
            manifest = release.prepare_dry_run(source, destination, now=now, env=env, baseline=baseline)
            if manifest.get('publicationAuthorized') is not False or manifest.get('purpose') != 'live-notion-dry-run':
                raise DryRunError('dry_run_publication_boundary')
            command = [node or shutil.which('node') or 'node', 'verify-release.cjs', '--check-only']
            # Environment is copied only after proving NOTION_TOKEN is absent.
            process = subprocess.run(command, cwd=destination, env=dict(env), capture_output=True, timeout=60)
            if process.returncode:
                raise DryRunError('release_verification_failed')
            verified = True
        except Exception:
            # Raw verifier/runtime messages are never copied to logs/artifacts.
            code = 'release_verification_failed'
    if code:
        state.update(ready=False, code=code, action='检查构建门槛与安全验证结果')
    state.update(verified=verified, publicationAuthorized=False, purpose='live-notion-dry-run')
    summary = collector.step_summary(data, error=diagnostics.get('code'), fetched=None)
    if data is None and diagnostics.get('notionErrors'):
        summary += '\n' + '\n'.join('- ' + collector.diagnostic_text(note) for note in diagnostics['notionErrors'][:20]) + '\n'
    summary += f'\n- 真实数据演练：{"通过" if state["ready"] and verified else "未通过"}；未发布。\n- 后续：{state["action"]}\n'
    names = export_artifact(artifact, data=data, snapshot=snapshot, summary=summary,
                            result=state, diagnostics=diagnostics)
    if env.get('GITHUB_STEP_SUMMARY'):
        with open(env['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as target:
            target.write(summary)
    return {**state, 'files': names}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--work', type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(source=args.bundle, destination=args.out, artifact=args.artifact,
                        baseline=args.baseline, work=args.work)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['ready'] and result['verified'] else 2
    except Exception:
        print(json.dumps({'ready': False, 'code': 'live_dry_run_failed', 'publicationAuthorized': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
