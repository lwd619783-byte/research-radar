"""Collect Notion then the unchanged bounded market pipeline, with a safe handoff.

Only this CLI reads NOTION_TOKEN. The research input is stripped to contract
properties before disk, and subsequent processing replays that file offline.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import os
from pathlib import Path
import platform
import re
import time

import acceptance_bundle as bundle
import acceptance_probe as probe
import build
from notion_normalize import normalize, simplify_page
from notion_source import TABLE_ORDER, fetch_all
from research_snapshot import ResearchAbort, canonical_json, load_last_good, snapshot_sha256
from research_view import CODE_TEXT
from execution_policy import dry_run_ref_allowed

REPOSITORY = 'lwd619783-byte/research-radar'
SOURCE_BRANCH = 'fix/radar-truthfulness-2026-10-18'
LIVE_BRANCH = 'v3/pr4-production'
TABLE_NAMES = dict(industries='行业', chokepoints='卡点', companies='公司',
                   financials='财报', daily='每日要点', weekly='每周主线')
EXECUTION_KEYS = ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'RUNNER_OS',
                  'RUNNER_ARCH', 'ImageOS', 'ImageVersion')
NOTION_CODES = frozenset(CODE_TEXT) | {'notion_bad_json', 'notion_http_error'}
# Enumerated from build.py / integrity.py. These are codes, never error text.
RELEASE_BLOCKER_CODES = frozenset({
    'stale_quotes_not_safe_in_all_frozen_views',
    'unconfirmed_close_or_intraday_needs_label_approval',
    'financial_evidence_incomplete', 'mixed_or_missing_market_dates_need_label_approval',
    'index_date_or_phase_needs_label_approval', 'index_observation_missing_or_stale',
    'ratio_extreme_conflicts_with_frozen_sentence', 'quotes_coverage_low',
    'synthetic_fixture_not_publishable', 'local_review_not_publishable', 'offline_not_publishable',
})
DIAGNOSTIC_CODES = NOTION_CODES | RELEASE_BLOCKER_CODES | {
    'contract_invalid', 'collection_failed', 'collection_execution_not_allowed', 'sensitive_notion_input'}
MARKET_ISSUE_STATUSES = {
    'daily': frozenset({'no_common_completed_observation', 'stale'}),
    'index': frozenset({'missing_or_unconfirmed_snapshot'}),
    'history': frozenset({'short_history'}),
    'ratio': frozenset({'frozen_text_or_range_incompatible', 'unavailable_or_short_history'}),
    'valuation': frozenset({'quote_date_mismatch_or_missing', 'quote_stale_or_invalid_receipt',
        'quote_observation_after_receipt', 'quote_currency_mismatch', 'market_cap_unavailable',
        'pe_missing', 'pe_nonpositive', 'pe_invalid', 'pe_not_meaningful'}),
}


def safe_market_issues(issues):
    """Only bounded codes, ticker characters and real ISO dates may leave collect."""
    if not isinstance(issues, list):
        return []
    result = []
    for item in issues[:100]:
        if not isinstance(item, dict):
            continue
        kind, status = item.get('kind'), item.get('status')
        if not isinstance(kind, str) or not isinstance(status, str) or status not in MARKET_ISSUE_STATUSES.get(kind, ()):
            continue
        row = {'kind': kind, 'status': status}
        symbol = item.get('symbol')
        if isinstance(symbol, str) and re.fullmatch(r'[A-Z0-9^][A-Z0-9.^=-]{0,23}', symbol) and not bundle.SECRET_VALUE.search(symbol):
            row['symbol'] = symbol
        for key in ('sourceDate', 'observedDate', 'requiredDate', 'expectedCompletedDate'):
            value = item.get(key)
            try:
                if isinstance(value, str) and dt.date.fromisoformat(value).isoformat() == value:
                    row[key] = value
            except ValueError:
                pass
        result.append(row)
    return result


def market_diagnostic_issues(data):
    """Attach dates already present in assembled metadata, without response data."""
    import market_calendar
    companies = {row.get('sym'): row for row in data.get('companies', [])}
    calendars = data.get('meta', {}).get('marketCalendar', {}).get('exchanges', {})
    enriched = []
    for issue in data.get('meta', {}).get('issues', []):
        if not isinstance(issue, dict):
            continue
        row = dict(issue)
        symbol = row.get('symbol')
        if row.get('kind') == 'daily':
            info = companies.get(symbol, {}).get('marketCalendar', {})
            row.update(sourceDate=info.get('quoteDate'), expectedCompletedDate=info.get('expectedCompletedDate'))
        elif row.get('kind') == 'index':
            info = calendars.get(market_calendar.exchange_for(symbol), {})
            row['expectedCompletedDate'] = info.get('expectedCompletedDate')
        enriched.append(row)
    return safe_market_issues(enriched)


def safe_collection_diagnostic(code, *, blockers=(), market_issues=(), notion_errors=()):
    code = code if isinstance(code, str) and code in DIAGNOSTIC_CODES else 'collection_failed'
    result = {'code': code, 'notionErrors': []}
    blockers = blockers if isinstance(blockers, (list, tuple)) else ()
    accepted = sorted({value for value in blockers if isinstance(value, str) and value in RELEASE_BLOCKER_CODES})
    if accepted:
        result['blockers'] = accepted
    issues = safe_market_issues(market_issues)
    if issues:
        result['marketIssues'] = issues
    notion_errors = notion_errors if isinstance(notion_errors, (list, tuple)) else ()
    for note in notion_errors[:20]:
        if not isinstance(note, dict):
            continue
        # Existing source errors are reduced again; no arbitrary detail strings.
        fields = {key: note[key] for key in ('code', 'http_status', 'notion_code') if key in note}
        if not isinstance(fields.get('code'), str):
            fields['code'] = None
        item = safe_error(fields,
                          note.get('table') if note.get('table') in TABLE_ORDER else None)
        result['notionErrors'].append(item)
    return result


def diagnostic_notion_errors(fetched):
    """A malformed handoff must not prevent writing the minimal safe failure."""
    tables = fetched.get('tables', {}) if isinstance(fetched, dict) else {}
    if not isinstance(tables, dict):
        return []
    return [table['error'] for name in TABLE_ORDER
            if isinstance(table := tables.get(name), dict) and isinstance(table.get('error'), dict)]


class CollectError(ValueError):
    """Only fixed codes leave this module; rejected inputs never enter messages."""


def admit(env, live_dry_run=False):
    ref_allowed = dry_run_ref_allowed(env) if live_dry_run else env.get('GITHUB_REF') == 'refs/heads/' + SOURCE_BRANCH
    events = ('workflow_dispatch',) if live_dry_run else ('schedule', 'push', 'workflow_dispatch')
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != REPOSITORY or
            not ref_allowed or
            env.get('GITHUB_EVENT_NAME') not in events or env.get('GITHUB_RUN_ATTEMPT') != '1' or
            not re.fullmatch(r'[0-9a-f]{40}', env.get('GITHUB_SHA', '')) or
            not re.fullmatch(r'[0-9]+', env.get('GITHUB_RUN_ID', ''))):
        raise CollectError('collection_execution_not_allowed')


def safe_error(error, table=None):
    error = error if isinstance(error, dict) else {}
    code = error.get('code')
    result = {'code': code if code in NOTION_CODES else 'notion_bad_json'}
    if table in TABLE_ORDER:
        result['table'] = table
    status = error.get('http_status')
    if isinstance(status, int) and 100 <= status <= 599:
        result['http_status'] = status
    notion_code = error.get('notion_code')
    if notion_code in ('unauthorized', 'restricted_resource', 'object_not_found',
                       'rate_limited', 'internal_server_error', 'service_unavailable',
                       'validation_error', 'conflict_error', 'invalid_request_url',
                       'invalid_request', 'missing_version', 'invalid_json'):
        result['notion_code'] = notion_code
    detail = error.get('detail')
    if isinstance(detail, dict):
        # Transport schema diagnostics have fixed keys. Other server text is not
        # useful for replay and must never be copied into artifacts.
        result['detail'] = {key: value for key, value in detail.items()
                            if key in ('prop', 'change', 'expected', 'actual') and
                            (value is None or isinstance(value, (str, int, bool)))}
    return result


def _scalar(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list):
        return [_scalar(item) for item in value if isinstance(item, (str, int, bool, float)) or item is None]
    return None


def sanitize_fetch(fetched, contract, *, fetched_at, sleeps=(), token=''):
    """The §8.1 disk format: flat schemas and simplified rows, no API identities."""
    result = {'schemaVersion': 1, 'fetchedAt': fetched_at,
              'requests': copy.deepcopy(fetched['request_stats']), 'sleeps': list(sleeps),
              'stopped_all': bool(fetched.get('stopped_all')), 'tables': {}}
    if result['stopped_all']:
        result['error'] = safe_error(fetched.get('error'))
    for name in TABLE_ORDER:
        source = fetched['tables'][name]
        spec = contract['tables'][name]
        allowed = {key for key, value in spec['properties'].items() if value['level'] != 'ignore'}
        schema = source.get('schema', {}).get('properties', {})
        table = {'ok': bool(source.get('ok')), 'code': None, 'detail': {},
                 'schema': {key: value.get('type') for key, value in schema.items()
                            if key in allowed and isinstance(value, dict)}, 'rows': []}
        if not table['ok']:
            error = safe_error(source.get('error') or fetched.get('error'), name)
            table.update(code=error['code'], detail=error.get('detail', {}), error=error)
        for page in source.get('pages', []):
            if page.get('object') != 'page':
                continue
            row = simplify_page(page, spec)
            row['props'] = {key: _scalar(value) for key, value in row['props'].items() if key in allowed}
            row['in_trash'] = page.get('in_trash') is True
            table['rows'].append(row)
        result['tables'][name] = table
    encoded = canonical_json(result)
    if token and token in encoded:
        raise CollectError('sensitive_notion_input')
    bundle.check_sensitive(result)
    return result


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(value)
    bundle.check_sensitive(value)
    temporary = path.with_name(path.name + '.tmp')
    try:
        temporary.write_text(data, encoding='utf-8', newline='\n')
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _cell(value):
    return re.sub(r'[\r\n\t]+', ' ', str(value or '')).replace('|', '／')[:120]


def diagnostic_text(note):
    code = note.get('code', '')
    if code == 'text_long' and not note.get('detail'):
        return '文字偏长：' + _cell(note.get('field') or '相关列') + '（建议缩短）'
    text = CODE_TEXT.get(code, code if re.fullmatch(r'[a-z_]{1,64}', code) else '数据处理未完成')
    detail = note.get('detail') or {}
    fields = {'表': TABLE_NAMES.get(note.get('table'), '研究'), '列名': note.get('field') or detail.get('prop') or '相关列',
              '状态码': note.get('http_status', '未知'), '原类型': detail.get('expected', '原类型'),
              '新类型': detail.get('actual', '新类型')}
    for key, value in fields.items():
        text = text.replace('{' + key + '}', _cell(value))
    return re.sub(r'\{[^{}]+\}', '相关值', text)


def step_summary(data=None, *, error=None, fetched=None):
    """Chinese §8.6 summary, limited to 20 safe diagnostic rows."""
    if data is None:
        code = error if error in DIAGNOSTIC_CODES else 'collection_failed'
        lines = ['### 投研雷达 · 本次更新未完成', '- 线上保持上一次成功版本。',
                 '- 原因：' + diagnostic_text({'code': code})]
        notes = [table.get('error') for table in (fetched or {}).get('tables', {}).values() if table.get('error')]
    else:
        meta = data['meta']; notion = meta.get('notion', {}); weekly = meta.get('weekly', {})
        stats = notion.get('requests') or {}; counts = notion.get('counts', {})
        stamp = dt.datetime.fromisoformat(meta['generatedAt']).astimezone(build.BJ)
        day = '日一二三四五六'[(stamp.weekday() + 1) % 7]
        blocked = bool(build.release_blockers(data))
        status = '（离线演练，不可发布）' if meta.get('reviewPreview') else ('未完成' if blocked else '✅')
        source = {'notion': 'Notion', 'partial': 'Notion（部分沿用）', 'last_good': '全部沿用上次版本'}.get(notion.get('source'), '仓库文件')
        tables = ' · '.join(f'{TABLE_NAMES[name]} {counts.get(name, {}).get("used", 0)}' for name in TABLE_ORDER)
        fallbacks = notion.get('fallbackTables', []); quarantined = notion.get('quarantined', []); warnings = notion.get('warnings', [])
        modes = {'ai': 'AI 研判', 'auto': '自动生成', 'stale': '待更新', 'none': '待更新'}
        daily = ' · '.join(market + ' ' + ('AI 摘要' if row.get('source') == 'ai' else '自动生成')
                           for market, row in meta.get('daily', {}).items())
        companies = data.get('companies', [])
        quotes = sum(isinstance(row.get('price'), (int, float)) and not isinstance(row.get('price'), bool)
                     and math.isfinite(row['price']) and row['price'] > 0 for row in companies)
        fx_ok = all(value in meta.get('fx', {}) for value in meta.get('requiredFX', []))
        next_run = meta.get('schedule', {}).get('nextRunAt')
        next_text = dt.datetime.fromisoformat(next_run).astimezone(build.BJ).strftime('%m/%d %H:%M') if next_run else '未配置'
        lines = [f'### 投研雷达 · {stamp.month}/{stamp.day} 周{day} {stamp:%H:%M} 更新 {status}',
                 f'- 研究数据：{source}（{stats.get("total", 0)} 次请求，{stats.get("retries", 0)} 次重试）· {tables}',
                 f'- 沿用上次版本：{"、".join(TABLE_NAMES[x["table"]] for x in fallbacks) or "无"} · 隔离：{len(quarantined)} 行 · 提醒：{len(warnings)} 条',
                 f'- 本周主线：{_cell(weekly.get("week"))} · {modes.get(weekly.get("mode"), "待更新")} · {_cell(weekly.get("focus"))}',
                 f'- 今日要点：{daily or "待更新"}',
                 f'- 行情：{quotes}/{len(companies)} 家 · 汇率 {"✅" if fx_ok else "缺失"} · 温度计 {"✅" if data.get("ratio") else "缺失"} · 下次 {next_text}']
        notes = [*fallbacks, *quarantined, *warnings]
    if notes:
        lines += ['', '| 表 | 行 | 问题 | 处理 |', '|---|---|---|---|']
        for note in notes[:20]:
            action = ('整表沿用 ' + str(note['lastGoodFetchedAt']) if note.get('lastGoodFetchedAt') else
                      '显示上次版本' if note.get('usedLastGood') else '保留缺项或待更新标记')
            lines.append('| ' + ' | '.join(_cell(value) for value in
                (TABLE_NAMES.get(note.get('table'), '研究'), note.get('key') or '—', diagnostic_text(note), action)) + ' |')
    result = '\n'.join(lines) + '\n'
    bundle.check_sensitive(result)
    return result


def write_summary(work, text, env):
    Path(work).mkdir(parents=True, exist_ok=True)
    (Path(work) / 'step-summary.md').write_text(text, encoding='utf-8', newline='\n')
    if env.get('GITHUB_STEP_SUMMARY'):
        with open(env['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as target:
            target.write(text)


def baseline_snapshot(path, contract):
    if path is None:
        return None
    root = Path(path)
    # A v2 release intentionally has no last-good Notion state.
    manifest = json.loads((root / 'release.json').read_text('utf-8'))
    if manifest.get('schemaVersion', 0) < 3:
        return None
    from release_operations import verify_files
    checked, _ = verify_files(root)
    snapshot = load_last_good(root / 'research-snapshot.json', contract)
    if snapshot is None or snapshot_sha256(snapshot) != checked.get('researchSnapshotSHA256'):
        raise CollectError('invalid_baseline_snapshot')
    return snapshot


def collect(*, out, work, baseline=None, token='', transport=None, market_collect=None,
            clock=None, env=None, live_dry_run=False, sleep=None, pace=None, last_good=None):
    """Dependency injection is test-only; the CLI exposes no fixture or clock options."""
    env = dict(env if env is not None else os.environ)
    env.pop('NOTION_TOKEN', None)
    admit(env, live_dry_run)
    out, work = Path(out), Path(work)
    if out.name != 'receipt.json' or out.parent.exists() or out.parent.is_symlink():
        raise CollectError('collection_destination_exists')
    if (work / 'notion-fetch.json').exists():
        raise CollectError('notion_handoff_exists')
    synthetic = transport is not None or market_collect is not None or clock is not None or last_good is not None
    now = clock or (lambda: dt.datetime.now(build.BJ))
    initial = now()
    config = build.research_config()
    contract = build.load_notion_contract(config)
    previous = last_good if last_good is not None else baseline_snapshot(baseline, contract)
    delays = []
    def retry_sleep(seconds):
        delays.append(seconds)
        (sleep or time.sleep)(seconds)
    raw = fetch_all(contract, config.get('notion', {}), token=token, transport=transport,
                    sleep=retry_sleep, pace=pace, fixed_clock=initial)
    fetched = sanitize_fetch(raw, contract, fetched_at=initial.isoformat(), sleeps=delays, token=token)
    token = None
    del raw
    save_json(work / 'notion-fetch.json', fetched)
    # Re-read the credential-free handoff exactly as later steps can. No Notion
    # transport, token, or environment access is available to normalization.
    fetched = json.loads((work / 'notion-fetch.json').read_text('utf-8'))
    research = normalize(fetched, contract, initial, last_good=previous, config=config)
    cfg_data, validation = build.load_and_validate(build.RADAR, build.REPO, initial.date())
    if validation.errors:
        raise ResearchAbort('contract_invalid')
    cfg_data.update(industries=research['industries'], chokepoints=research['chokepoints'], companies=research['companies'])
    budget = probe.Budget()
    selected = {}
    market = {}
    kwargs = {'snapshot_sink': selected, 'market_sink': market}
    if market_collect is None:
        kwargs['calendar_policy'] = True
    if clock is not None:
        kwargs['snapshot_clock'] = now()
    rows, summary, session, gates = (market_collect or probe.collect)(cfg_data, budget, **kwargs)
    final_clock = selected['clock']
    research = normalize(fetched, contract, final_clock, last_good=previous, config=config)
    data = build.apply_research(selected['data'], research, final_clock, config)
    if synthetic:
        data['meta']['reviewPreview'] = True
    available = sum(isinstance(row.get('price'), (int, float)) and not isinstance(row.get('price'), bool)
                    and math.isfinite(row['price']) and row['price'] > 0 for row in data['companies'])
    if not data['companies'] or available / len(data['companies']) < .70:
        data['meta'].setdefault('blockers', []).append('quotes_coverage_low')
    snapshot = research['snapshot']
    blockers = build.release_blockers(data)
    gates.update(blockers=blockers, dataSHA256=bundle.data_digest(data),
                 asOf=data['meta']['asOf'], snapshot=data['meta']['snapshot'],
                 asOfByMarket=data['meta']['asOfByMarket'], coverage=data['meta'].get('coverage', []),
                 financialRequired=len(data['companies']),
                 financialVerified=sum((c.get('provenance', {}).get('financial') or {}).get('evidence') == 'source' for c in data['companies']),
                 financialPartial=sum((c.get('provenance', {}).get('financial') or {}).get('evidence') == 'partial' for c in data['companies']),
                 researchSnapshotSHA256=snapshot_sha256(snapshot))
    purpose = 'offline-rehearsal' if synthetic else 'live-notion-dry-run' if live_dry_run else 'production-collection'
    receipt = {'schemaVersion': 1, 'purpose': purpose, 'startedAt': initial.isoformat(),
        'execution': {key: env.get(key) for key in EXECUTION_KEYS},
        'python': platform.python_version(), 'kernel': platform.release(),
        'limits': {'requests': probe.MAX_REQUESTS, 'timeoutSeconds': probe.TIMEOUT,
                   'deadlineSeconds': probe.DEADLINE, 'attemptsPerGet': 2, 'retryOnly429': True,
                   'maxRetryAfterSeconds': 10},
        'results': rows, 'summary': summary, 'quoteSession': session, 'publication': gates,
        'requestsMade': budget.count, 'deniedPaths': sorted(budget.denied),
        'finishedAt': final_clock.isoformat(), 'fixedClock': final_clock.isoformat(),
        'notion': {'requests': fetched['requests'], 'fetchSHA256': bundle.digest((work / 'notion-fetch.json').read_bytes())}}
    text = step_summary(data)
    write_summary(work, text, env)
    real_blockers = [code for code in blockers if code not in
                     ('synthetic_fixture_not_publishable', 'local_review_not_publishable', 'offline_not_publishable')]
    if real_blockers:
        save_json(work / 'diagnostic.json', safe_collection_diagnostic(real_blockers[0], blockers=real_blockers,
                  market_issues=market_diagnostic_issues(data),
                  notion_errors=diagnostic_notion_errors(fetched)))
        raise ResearchAbort(real_blockers[0], codes=real_blockers)
    saved = bundle.write_bundle(out.parent, data, receipt, final_clock, research_snapshot=snapshot)
    return {'archive': saved, 'data': data, 'receipt': receipt, 'snapshot': snapshot,
            'summary': text, 'blocked': bool(blockers), 'purpose': purpose}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--live-dry-run', action='store_true')
    args = parser.parse_args(argv)
    # Remove the secret before any subprocess or downstream phase can inherit it.
    token = os.environ.pop('NOTION_TOKEN', '')
    try:
        result = collect(out=args.out, work=args.work, baseline=args.baseline, token=token,
                         live_dry_run=args.live_dry_run)
        print(json.dumps({'collected': True, 'publicationAuthorized': False,
                          'blocked': result['blocked'], 'purpose': result['purpose']}))
        return 2 if result['blocked'] else 0
    except Exception as error:
        code = error.code if isinstance(error, ResearchAbort) else (
            str(error) if isinstance(error, CollectError) else 'collection_failed')
        if not isinstance(code, str) or code not in DIAGNOSTIC_CODES:
            code = 'collection_failed'
        fetched = None
        try:
            path = args.work / 'notion-fetch.json'
            if path.is_file():
                fetched = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            pass
        try:
            previous = {}
            diagnostic_path = args.work / 'diagnostic.json'
            if isinstance(error, ResearchAbort) and error.code in RELEASE_BLOCKER_CODES and diagnostic_path.is_file():
                # Only the current controlled failure can preserve earlier codes.
                try:
                    candidate = json.loads(diagnostic_path.read_text('utf-8'))
                    if isinstance(candidate, dict) and candidate.get('code') == code:
                        previous = candidate
                except (OSError, ValueError):
                    pass
            blockers = error.codes if isinstance(error, ResearchAbort) else []
            previous_blockers = previous.get('blockers', [])
            if not isinstance(previous_blockers, list):
                previous_blockers = []
            diagnostic = safe_collection_diagnostic(code, blockers=[*blockers, *previous_blockers],
                market_issues=previous.get('marketIssues', []),
                notion_errors=diagnostic_notion_errors(fetched))
            save_json(diagnostic_path, diagnostic)
            text = step_summary(error=diagnostic['code'], fetched={'tables': {
                str(i): {'error': note} for i, note in enumerate(diagnostic['notionErrors'])}})
            write_summary(args.work, text, os.environ)
        except Exception:
            pass
        print(json.dumps({'collected': False, 'code': code, 'publicationAuthorized': False}))
        return 2 if isinstance(error, (ResearchAbort, CollectError)) else 1


if __name__ == '__main__':
    raise SystemExit(main())
