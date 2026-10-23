"""Escaped, deterministic first-screen HTML for readers with JavaScript disabled."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import math
from urllib.parse import urlsplit

from research_view import CODE_TEXT

DISCLAIMER = '研究内容由 AI 依据公开资料撰写，程序自动检查格式、日期与来源，未经人工审核；行情由定时任务更新。仅供研究参考，不构成投资建议。'


def esc(value):
    return escape('' if value is None else str(value), quote=True)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def date(value):
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def short_date(value, today=None, weekday=False):
    value = date(value)
    if not value:
        return '日期未提供'
    prefix = f'{value.year}/' if today and value.year != today.year else ''
    return prefix + f'{value.month}/{value.day}' + (' 周' + '一二三四五六日'[value.weekday()] if weekday else '')


def short_time(value, today=None):
    try:
        timestamp = dt.datetime.fromisoformat(str(value)).astimezone(dt.timezone(dt.timedelta(hours=8)))
    except (ValueError, TypeError):
        return '时间未提供'
    return short_date(timestamp.date(), today) + ' ' + timestamp.strftime('%H:%M')


def safe_url(value):
    if not isinstance(value, str) or any(ord(char) <= 32 for char in value):
        return ''
    try:
        parts = urlsplit(value)
        return value if parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password else ''
    except ValueError:
        return ''


def link(url, text, css=''):
    url = safe_url(url)
    if not url:
        return ''
    return f'<a class="{esc(css)}" href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)} ↗</a>'


def pct(value):
    if not number(value):
        return '—'
    rounded = (Decimal(str(value)) * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return ('+' if rounded > 0 else '−' if rounded < 0 else '') + f'{abs(rounded):,.2f}%'


def label(kind, text, tooltip):
    kind = kind if kind in ('ai', 'stale', 'auto', 'conflict') else 'stale'
    return f'<span class="st {kind}" tabindex="0" data-tip="{esc(tooltip)}" aria-label="{esc(tooltip)}">{esc(text)}</span>'


def reason_text(reason, judgment):
    text = CODE_TEXT.get(reason, '研判信息待更新')
    return text.replace('{日期}', str(judgment.get('validUntil') or '未提供'))


def hero_provenance(weekly, today):
    mode = weekly.get('mode', 'stale')
    judgment = weekly.get('judgment') or {}
    if mode == 'none':
        return ''
    if mode == 'auto':
        return label('auto', '自动生成', '按行业评分与卡点数据自动生成，不代表新的 AI 研判') + '<span>本周还没有主线研判 · 按行业评分自动选出</span>'
    reasons = judgment.get('reasons') or ([] if mode == 'ai' else ['legacy_data'])
    tooltip = '；'.join(reason_text(reason, judgment) for reason in reasons) or 'AI 依据公开资料撰写的研究判断'
    badge = label('ai' if mode == 'ai' else 'stale', 'AI 研判' if mode == 'ai' else '待更新', tooltip)
    first = f'{short_date(judgment.get("date"), today)} 研判' if judgment.get('date') else '旧版数据，无研判信息'
    second = f'有效至 {short_date(judgment.get("validUntil"), today)}' if judgment.get('validUntil') else ''
    if mode == 'stale':
        if 'expired' in reasons:
            second += '，已过期'
        elif 'not_current_week' in reasons:
            second = '不是本周的研判'
        elif reasons and reasons[0] != 'legacy_data':
            second = reason_text(reasons[0], judgment)
    parts = [badge, f'<span class="num">{esc(first)}</span>']
    if second:
        parts += ['<span class="sep">·</span>', f'<span>{esc(second)}</span>']
    if mode == 'stale':
        parts += ['<span class="sep">·</span><span>显示上次结论</span>']
    else:
        parts += [f'<span class="opt"><span class="sep">·</span> 依据 <b class="num">{len(judgment.get("sources") or [])}</b> 条</span>']
    parts += ['<span class="sep">·</span><a href="#researchReason" class="js-only" data-reason="weekly" aria-haspopup="dialog">查看理由</a>']
    return ''.join(parts)


def render_today(meta, today):
    daily = meta.get('daily') or {}
    markets = ('A股', '美股')
    badge = label('ai', 'AI 摘要', 'AI 根据当日收盘复盘写的一句话，只陈述已发生的事实，不做预测。') if all(daily.get(m, {}).get('source') == 'ai' for m in markets) else ''
    rows = []
    for market in markets:
        row = daily.get(market) or {}
        automatic = row.get('source') == 'auto'
        line = row.get('line') or '今日要点待更新'
        metadata = f'<span class="today-mk">{market}</span><span class="num">{esc(short_date(row.get("date"), today, weekday=True))} · 收盘</span>'
        if row.get('source') == 'ai':
            metadata += link(row.get('reviewUrl'), '看复盘', 'today-go')
        chips = ''.join(f'<span>{esc(chip.get("label"))}<b class="{"up" if number(chip.get("chg")) and chip["chg"] > 0 else "down" if number(chip.get("chg")) and chip["chg"] < 0 else "flat"}">{pct(chip.get("chg"))}</b></span>' for chip in (row.get('chips') or []))
        suffix = '<div class="today-tags">' + label('auto', '自动生成', '复盘未更新，依据已完成交易日的指数变化生成') + '<span class="hint">复盘未更新</span></div>' if automatic else ''
        source_attr = ' data-src="notion"' if row.get('source') == 'ai' else ''
        rows.append(f'<div class="today-row{" is-auto" if automatic else ""}"><div class="today-meta">{metadata}</div><p class="today-line"{source_attr}>{esc(line)}</p><div class="today-ix num">{chips}</div>{suffix}</div>')
    return '<div class="today-h"><span class="today-t">今日要点</span>' + badge + '<span class="hint">每个交易日收盘后更新</span></div><div class="today-rows">' + ''.join(rows) + '</div>'


def kpi_values(data):
    """Same inclusive 14-day window and financial signal as the existing UI."""
    industries = data.get('industries') or []
    points = data.get('chokepoints') or []
    companies = data.get('companies') or []
    today = date(data.get('meta', {}).get('today'))
    focused = [row for row in industries if number(row.get('total')) and row['total'] >= 17]
    stale = sum((row.get('judgment') or {}).get('label', 'stale') != 'ai' for row in focused)
    events = [row for row in companies if today and date(row.get('next')) and today <= date(row['next']) <= today + dt.timedelta(days=14)]
    confirmed = sum((row.get('earnings') or {}).get('status') == 'confirmed'
                    and safe_url((row.get('earnings') or {}).get('source_url', '')).startswith('https://') for row in events)
    high_growth = sum(not row.get('financialPartial') and bool(row.get('financialSignalEligible'))
                      and number(row.get('earng') if number(row.get('earng')) else row.get('revg'))
                      and (row['earng'] if number(row.get('earng')) else row['revg']) >= .5 for row in companies)
    return [
        (len(focused), '重点追踪行业', '总分 ≥ 17' + (f' · {stale} 个待更新' if stale else ''), 'gold'),
        (sum(row.get('tight') in ('🔴极紧', '极紧') for row in points), '极紧卡点', f'共 {len(points)} 个', 'tight'),
        (high_growth, '业绩高增龙头', f'同比 ≥ 50% · 共 {len(companies)} 家', 'up'),
        (sum(number(row.get('dd52')) and row['dd52'] <= -.4 for row in companies), '深度回调龙头', '距52周高点 ≤ −40%', 'down'),
        (len(events), '两周内财报', f'官方确认 {confirmed} · 预估 {len(events) - confirmed}', 'accent-2'),
    ]


def render_kpis(data):
    # Existing icon paths, rather than an additional icon library or vocabulary.
    paths = [
        '<path d="M12 22c4.4 0 7.5-2.9 7.5-7.2 0-3.1-2-5.6-3.6-7.2-.3 2-1.5 3.1-2.6 3.1.5-3.1-1-6.2-4.1-8.2 0 3.1-1.5 5.1-3.1 6.7C4.6 10.8 4.5 12.6 4.5 14.8 4.5 19.1 7.6 22 12 22z"/>',
        '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
        '<path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/>',
        '<path d="M3 7l6 6 4-4 8 8"/><path d="M14 17h7v-7"/>',
        '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    ]
    rows = []
    for (value, title, subtitle, color), path in zip(kpi_values(data), paths):
        icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + path + '</svg>'
        rows.append(f'<div class="kpi" style="--c:var(--{color})"><span class="ic">{icon}</span><span class="v num" data-count="{value}">{value:,}</span><span class="l">{title}<small>{esc(subtitle)}</small></span></div>')
    return ''.join(rows)


def render_pulse(data, today, operations=None):
    meta = data.get('meta') or {}
    if (operations or {}).get('state') == 'failed':
        generated = short_time(meta.get('generatedAt'), today)
        schedule = meta.get('schedule') or {}
        next_run = schedule.get('nextRunAt')
        if operations.get('attemptedAt') and schedule.get('cronUtc'):
            from release_schedule import schedule_metadata
            next_run = schedule_metadata({'cron_utc': schedule['cronUtc'],
                'late_after_minutes': schedule.get('lateAfterMinutes', 90)}, operations['attemptedAt'])['nextRunAt']
        following = f'<span class="sep">·</span><span>下次 <b class="num">{esc(short_time(next_run, today))}</b></span>' if next_run else ''
        return ('<span class="dot bad" aria-hidden="true"></span>'
                f'<span class="msg-bad">本次更新未完成，显示 {esc(generated)} 的数据</span>' + following +
                '<span class="sep">·</span><a href="#dataNotes">数据说明</a>')
    notion = meta.get('notion') or {}
    fallback = notion.get('fallbackTables') or []
    quarantined = notion.get('quarantined') or []
    problems = []
    if len(fallback) == 6:
        dates = [row.get('lastGoodFetchedAt') for row in fallback if row.get('lastGoodFetchedAt')]
        problems.append('研究数据未更新，沿用 ' + short_time(min(dates) if dates else None, today) + ' 的版本')
    elif fallback:
        problems.append(f'{len(fallback)} 张研究表沿用上次版本')
    if quarantined:
        problems.append(f'{len(quarantined)} 行研究数据有误，已沿用上次版本或暂不显示')
    # assemble() identifies cached or outdated daily observations by company
    # name in meta.stale; DATA can still carry a non-null previous price.
    missing_markers = meta.get('missing') or []
    stale = set(meta.get('stale') or []) | set(missing_markers if isinstance(missing_markers, list) else [])
    daily_gaps = {issue.get('symbol') for issue in meta.get('issues', [])
                  if issue.get('kind') == 'daily' and issue.get('status') in ('stale', 'no_common_completed_observation')}
    missing = cached = 0
    for row in data.get('companies', []):
        if not number(row.get('price')):
            missing += 1
        elif (row.get('stale') or any(row.get(key) in stale for key in ('id', 'name', 'sym'))
              or row.get('sym') in daily_gaps):
            cached += 1
    quotes = []
    if missing:
        quotes.append(f'{missing} 家行情暂缺')
    if cached:
        quotes.append(f'{cached} 家行情暂缺，显示上次值')
    if quotes:
        problems.append('；'.join(quotes))
    parts = [f'<span class="dot{" warn" if problems else ""}" aria-hidden="true"></span>',
             f'<span>行情更新于 <b class="num">{esc(short_time(meta.get("generatedAt"), today))}</b></span>']
    if problems:
        parts += [f'<span class="msg-warn">{esc(problem)}</span>' for problem in problems[:2]]
    else:
        next_run = (meta.get('schedule') or {}).get('nextRunAt')
        if next_run:
            parts.append(f'<span>下次 <b class="num">{esc(short_time(next_run, today))}</b></span>')
        summary = (operations or {}).get('changes') or data.get('changes') or {}
        changes = (summary.get('today') or (operations or {}).get('changesToday')
                   or summary.get('changesToday') or meta.get('changesToday'))
        if (changes is None or summary.get('mode') == 'unavailable' or changes.get('firstRun')
                or changes.get('firstUpdate') or changes.get('mode') == 'first_update'):
            parts.append('<span>今日变化：首次更新</span>')
        else:
            def count(*names):
                value = next((changes[name] for name in names if name in changes), [])
                return len(value) if isinstance(value, list) else value if isinstance(value, int) else 0
            parts.append(f'<span>今日变化：财报 <b class="num">{count("reports", "financials")}</b> · 财报日确认 <b class="num">{count("confirmed", "calendar", "earningsConfirmed")}</b> · 评分 <b class="num">{count("scores")}</b></span>')
    parts.append('<a href="#dataNotes">数据说明</a>')
    return '<span class="sep">·</span>'.join(parts)


def render_footer(data, today):
    notion = data.get('meta', {}).get('notion')
    description = '研究数据：仓库文件'
    if notion:
        requests = notion.get('requests', 0)
        if isinstance(requests, dict):
            requests = requests.get('total', 0)
        description = '研究数据：来自 Notion · 读取于 ' + short_time(notion.get('fetchedAt'), today) + f' · {requests} 次请求'
    warnings = (data.get('meta', {}).get('marketCalendar') or {}).get('warnings') or []
    warnings = [value for value in warnings if isinstance(value, str) and value]
    calendar_notes = '<ul>' + ''.join(f'<li>{esc(value)}</li>' for value in warnings) + '</ul>' if warnings else ''
    return f'<div id="dataNotes"><div class="bl">数据说明</div><p>{esc(description)}</p>{calendar_notes}</div><p class="disclaimer" id="disclaimer">{DISCLAIMER}</p>'


def render_fragments(data, operations=None):
    meta = data.get('meta') or {}
    weekly = meta.get('weekly') or {}
    today = date(meta.get('today'))
    week = f'{today.isocalendar().year}-W{today.isocalendar().week:02}' if today else weekly.get('week') or ''
    dates = ''
    if today:
        monday = today - dt.timedelta(days=today.weekday())
        dates = f'{short_date(monday, today)}–{short_date(monday + dt.timedelta(days=6), today)}'
    none = weekly.get('mode') == 'none'
    focus = weekly.get('focus') or next((row.get('name') for row in data.get('industries', [])), '')
    title = '本周主线待更新' if none or not focus else '本周主线：<span class="grad" data-src="notion">' + esc(focus) + '</span>'
    return {
        'HERO_DATE': esc(week + (' · ' + dates if dates else '')),
        'HERO_TITLE': title,
        'HERO_PROV': hero_provenance(weekly, today),
        'HERO_LEAD': esc('行业研判均待更新，下方数据照常显示。' if none else weekly.get('lead') or ''),
        'TODAY': render_today(meta, today), 'KPIS': render_kpis(data),
        'PULSE': render_pulse(data, today, operations), 'NOSCRIPT': '', 'FOOT': render_footer(data, today),
    }


def render_into(template, data, operations=None):
    for key, fragment in render_fragments(data, operations).items():
        template = template.replace('<!--__SSR_' + key + '__-->', fragment)
    return template
