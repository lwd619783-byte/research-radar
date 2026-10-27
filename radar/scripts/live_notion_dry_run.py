"""Verify a real manual Notion dry-run and export only safe review diagnostics."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import acceptance_bundle as bundle
import production_collect as collector
import production_release as release
from research_snapshot import canonical_json


class DryRunError(ValueError):
    pass


NOTION_FAILURES = {
    'notion_timeout': '读取超时或连接失败，检查连接后重新演练',
    'notion_rate_limited': '限流重试后仍失败，稍后新建一次演练',
    'notion_server_error': '服务端重试后仍失败，稍后新建一次演练',
    'notion_schema_changed': '表结构与契约不一致，按安全诊断恢复约定列名和类型后重新演练',
    'table_quality_low': '异常行超过门槛，按隔离记录修复原行后重新演练',
    'notion_bad_json': '返回内容无法解析，检查安全诊断后重新演练',
    'notion_http_error': '请求失败，检查安全诊断中的状态码后重新演练',
    'notion_cursor_loop': '分页游标重复，检查数据源分页后重新演练',
    'notion_too_many_pages': '分页超过读取上限，检查数据源规模后重新演练',
    'notion_body_too_large': '响应超过读取上限，检查数据源响应后重新演练',
}
WEEKLY_FAILURES = {
    'no_weekly_row': '没有可用的本周主线记录',
    'not_current_week': '当前显示的记录不是本周周次',
    'expired': '研判已过有效期，需实质复评后更新研判日期和有效至',
    'missing_reason': '缺研判理由',
    'missing_source': '缺有效来源链接',
    'missing_dates': '缺研判日期或有效至',
    'future_judgment_date': '研判日期晚于演练日期',
    'validity_too_long': '有效期超过 14 天',
    'banned_words': '内容含禁用词',
    'prediction_words': '内容含预测性用词',
    'row_quarantined': '原行被隔离，需按隔离记录修复',
    'missing_required': '缺必填项，需按隔离记录补齐',
    'regex_mismatch': '字段格式不符合契约',
    'relation_missing': '关联行业不存在或不可用',
    'relation_multiple': '关联行业数量不符合契约',
    'duplicate_key': '存在重复周次，需按隔离记录修复',
    'url_invalid': '来源链接不是有效 https 链接',
}


def _notion_actions(notes):
    """Only fixed table names and messages enter operator-facing diagnostics."""
    actions = []
    for note in notes:
        table = collector.TABLE_NAMES.get(note.get('table'), '研究数据')
        action = NOTION_FAILURES.get(note.get('code'), '读取或校验失败，检查安全诊断后重新演练')
        text = f'{table}：{action}'
        if text not in actions:
            actions.append(text)
    return '；'.join(actions)


def _weekly_action(meta):
    weekly = meta.get('weekly', {})
    week = weekly.get('week', '')
    # Never echo arbitrary Notion text, raw error details or unknown codes.
    week = week if isinstance(week, str) and re.fullmatch(r'[0-9]{4}-W[0-9]{2}', week) else ''
    reasons = list(weekly.get('judgment', {}).get('reasons', []))
    notion = meta.get('notion', {})
    for note in [*notion.get('warnings', []), *notion.get('quarantined', [])]:
        if week and note.get('table') == 'weekly' and note.get('key') == week:
            reasons.append(note.get('code'))
    messages = list(dict.fromkeys(WEEKLY_FAILURES[code] for code in reasons if code in WEEKLY_FAILURES))
    if not messages:
        messages = [{'auto': '当前主线为自动生成内容', 'none': '没有可用的本周主线记录',
                     'stale': '当前主线待更新'}.get(weekly.get('mode'), '本周主线未达到 AI 研判条件')]
    target = f'（{week}）' if week else ''
    return ('；'.join(messages) + f'。请按《维护规则》的周度复评要求，在每周主线表新增或修复本周{target}记录，'
            '核实研判理由、来源、研判日期和有效至后重新演练；不要只延长日期。')


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
        notes = (diagnostics or {}).get('notionErrors', [])
        return {'ready': False, 'code': 'live_collection_failed',
                'action': _notion_actions(notes) if notes else '检查安全诊断与行情来源状态'}
    if fallback:
        return {'ready': False, 'code': 'live_notion_fallback',
                'action': '本次有表沿用上次版本。' + _notion_actions(fallback)}
    if data['meta'].get('weekly', {}).get('mode') != 'ai':
        return {'ready': False, 'code': 'weekly_refresh_required',
                'action': _weekly_action(data['meta'])}
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
        diagnostics = collector.read_diagnostic(Path(work) / 'diagnostic.json')
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
