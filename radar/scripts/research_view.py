"""Pure V3 research views. No network, filesystem, or wall-clock reads."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
import re
import statistics
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


BJ = ZoneInfo('Asia/Shanghai')
DEFAULT_DAILY = {
    'markets': ['A股', '美股'],
    'chips': {'A股': ['000001.SS', '399006.SZ', 'HSTECH.HK'],
              '美股': ['^IXIC', '^GSPC', '^SOX']},
    'short': {'000001.SS': '上证', '399006.SZ': '创业板', 'HSTECH.HK': '恒生科技',
              '^IXIC': '纳指', '^GSPC': '标普500', '^SOX': '费城半导体'},
}


def as_date(value):
    if isinstance(value, dt.datetime):
        return value.astimezone(BJ).date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def is_notion_url(value):
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme in ('https', 'http') and not parsed.username and not parsed.password
                and any(host == domain or host.endswith('.' + domain)
                        for domain in ('notion.so', 'notion.site', 'notion.com')))
    except (TypeError, ValueError):
        return False


def public_first_sources(values):
    """Stable display order; source admission and original row contents are unchanged."""
    return sorted(dict.fromkeys(values), key=is_notion_url)


def urls(text):
    return public_first_sources(re.findall(r'''https?://[^\s<>"'）)]+''', text or ''))


def iso_week(today):
    year, week, _ = today.isocalendar()
    return f'{year:04}-W{week:02}'


def judgment(props, today, substituted=False, banned=False, source_week=None):
    today = as_date(today)
    reason = props.get('研判理由') or ''
    sources = urls(props.get('来源'))
    date = as_date(props.get('研判日期'))
    until = as_date(props.get('有效至'))
    reasons = []
    if source_week is not None and source_week != iso_week(today):
        reasons.append('not_current_week')
    if not reason:
        reasons.append('missing_reason')
    if not sources:
        reasons.append('missing_source')
    if date is None or until is None:
        reasons.append('missing_dates')
    else:
        if date > today:
            reasons.append('future_judgment_date')
        if until < today:
            reasons.append('expired')
        if (until - date).days > 14:
            reasons.append('validity_too_long')
    if banned:
        reasons.append('banned_words')
    if substituted:
        reasons.append('row_quarantined')
    return {'label': 'stale' if reasons else 'ai', 'reasons': reasons,
            'date': date.isoformat() if date else None,
            'validUntil': until.isoformat() if until else None,
            'reason': reason, 'sources': sources}


def rounded(value, places):
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def tight_rank(value):
    return next((score for word, score in [('极紧', 5), ('偏紧', 4), ('缓解中', 2)]
                 if word in (value or '')), 0)


def add_anchors(industries, chokepoints, companies):
    for industry in industries:
        name = industry['name']
        anchors = {}
        values = [Decimal(str(c['revg'])) * 100 for c in companies
                  if c['ind'] == name and c.get('financialRevenueComparable') and c.get('revg') is not None]
        if len(values) >= 3:
            median = rounded(statistics.median(values), 1)
            anchor = next((score for floor, score in [(50, 5), (25, 4), (10, 3), (-10, 2)]
                           if median >= floor), 1)
            anchors['业绩兑现'] = {'anchor': anchor, 'n': len(values), 'medianRevenueYoYPct': float(median)}
        points = [c for c in chokepoints if c['ind'] == name]
        if points:
            strongest = max(tight_rank(c['tight']) for c in points)
            anchors['卡点强度'] = {'anchor': strongest, 'n': len(points),
                                    'maxTightness': {5: '极紧', 4: '偏紧', 2: '缓解中'}[strongest]}
        industry['judgment']['anchors'] = anchors
        industry['judgment']['conflicts'] = [{'field': field, 'ai': industry['s'][position], 'anchor': anchors[field]['anchor']}
                                 for field, position in [('业绩兑现', 1), ('卡点强度', 2)]
                                 if field in anchors and abs(industry['s'][position] - anchors[field]['anchor']) >= 2]


def calendar_hint(companies, start, end):
    count = sum(bool(c.get('next') and start <= c['next'] <= end) for c in companies)
    return f'本周 {count} 家公司预计发布财报' if count else ''


def weekly_view(rows, industries, chokepoints, companies, today, internal=None):
    internal = internal or {}
    today = as_date(today)
    week = iso_week(today)
    start = (today - dt.timedelta(days=today.weekday())).isoformat()
    end = (today + dt.timedelta(days=6 - today.weekday())).isoformat()
    result = {'week': week, 'weekStart': start, 'weekEnd': end, 'sourceWeek': '',
              'mode': 'none', 'focus': '', 'lead': '', 'calHint': '',
              'judgment': {'label': 'stale', 'reasons': ['no_weekly_row'], 'date': None,
                           'validUntil': None, 'reason': '', 'sources': []}}
    candidates = []
    names = internal.get('industry_names', {})
    for row in rows:
        p = row['props']
        source_week = p.get('周次', '')
        if source_week > week or row.get('banned'):
            continue
        j = judgment(p, today, row.get('substituted', False), row.get('banned', False), source_week)
        candidates.append((row, j))
    candidates.sort(key=lambda pair: pair[0]['id'])
    candidates.sort(key=lambda pair: (pair[1]['date'] or '', pair[0]['props'].get('周次', '')), reverse=True)
    current = [pair for pair in candidates if pair[0]['props'].get('周次') == week and pair[1]['label'] == 'ai']
    recent = [pair for pair in candidates if pair[1]['date'] and 0 <= (today - as_date(pair[1]['date'])).days <= 14]
    selected = (current or recent)
    if selected:
        row, j = selected[0]
        p = row['props']
        relation = p.get('主线行业') or []
        focus = names.get(relation[0], relation[0]) if relation else ''
        result.update(sourceWeek=p['周次'], mode='ai' if current else 'stale', focus=focus,
                      lead=p.get('导语', ''), calHint=p.get('日历提示') or calendar_hint(companies, start, end), judgment=j)
        if not current:
            j['label'] = 'stale'
    else:
        eligible = [i for i in industries if i['judgment']['label'] == 'ai']
        if eligible:
            top = eligible[0]
            lead = f'本周综合分最高：「{top["name"]}」（{top["total"]}/20）'
            points = [c for c in chokepoints if c['ind'] == top['name']]
            order = internal.get('chokepoint_order', {})
            points.sort(key=lambda c: (-tight_rank(c['tight']), order.get(c['name'], 9999), c['name']))
            if points:
                lead += f'；最紧卡点「{points[0]["name"]}」'
            result.update(mode='auto', focus=top['name'], lead=lead + '。', calHint=calendar_hint(companies, start, end))
            result['judgment']['label'] = 'auto'
    return result


def daily_template(chips, indices):
    by_symbol = {i['symbol']: i for i in indices}
    values = [(by_symbol[c['symbol']].get('name', c['label']), rounded(Decimal(str(c['chg'])) * 100, 2))
              for c in chips]
    if not values:
        return ''
    high = max(values, key=lambda item: item[1])
    low = min(values, key=lambda item: item[1])
    up = any(value > 0 for _, value in values)
    down = any(value < 0 for _, value in values)
    flat = any(value == 0 for _, value in values)
    if up and down:
        return f'主要指数涨跌互现，{high[0]} +{high[1]:.2f}%，{low[0]} −{abs(low[1]):.2f}%'
    if up:
        prefix = '主要指数未见下跌' if flat else '主要指数集体上涨'
        return f'{prefix}，{high[0]}涨 {high[1]:.2f}% 领涨'
    if down:
        prefix = '主要指数未见上涨' if flat else '主要指数集体下跌'
        return f'{prefix}，{low[0]}跌 {abs(low[1]):.2f}% 领跌'
    return '主要指数基本持平'


def daily_view(rows, indices, trading_days, warnings, config=None, internal=None):
    config = config or DEFAULT_DAILY
    internal = internal or {}
    names = internal.get('industry_names', {})
    index_map = {i['symbol']: i for i in indices}
    result = {}
    for market in config.get('markets', DEFAULT_DAILY['markets']):
        target = trading_days.get(market)
        if isinstance(target, list):
            target = max(target, default=None)
        chips = []
        for symbol in config.get('chips', DEFAULT_DAILY['chips']).get(market, []):
            index = index_map.get(symbol, {})
            if target and index.get('asOf') == target and isinstance(index.get('chg'), (int, float)):
                chips.append({'symbol': symbol, 'label': config.get('short', DEFAULT_DAILY['short']).get(symbol, index.get('name', symbol)),
                              'chg': index['chg']})
        candidates = []
        for row in rows:
            p = row['props']
            if p.get('市场') != market:
                continue
            if target and p.get('日期') and p['日期'] > target:
                warnings.append({'code': 'daily_future_date', 'table': 'daily', 'key': p.get('标题', ''), 'field': '日期'})
            elif p.get('日期') == target and p.get('一句话') and not row.get('banned'):
                candidates.append(row)
        candidates.sort(key=lambda r: r['id'])
        candidates.sort(key=lambda r: r.get('last_edited_time', ''), reverse=True)
        if len(candidates) > 1:
            warnings.append({'code': 'daily_duplicate', 'table': 'daily', 'key': candidates[0]['props'].get('标题', ''), 'field': '日期'})
        p = candidates[0]['props'] if candidates else {}
        result[market] = {'date': target, 'source': 'ai' if candidates else 'auto',
                          'line': p.get('一句话', '') if candidates else daily_template(chips, indices),
                          'reviewUrl': p.get('复盘链接', ''),
                          'industries': [names.get(i, i) for i in p.get('涉及行业', [])], 'chips': chips}
    return result


def kpis(industries, chokepoints, companies):
    focus = [i for i in industries if i['total'] >= 17]
    return {'focusIndustries': len(focus),
            'focusIndustriesStale': sum(i['judgment']['label'] != 'ai' for i in focus),
            'tightChokepoints': sum(tight_rank(c['tight']) == 5 for c in chokepoints),
            'chokepointsTotal': len(chokepoints), 'companies': len(companies),
            'earningsConfirmed': sum(bool(c.get('next')) and c['earnings']['status'] == 'confirmed' for c in companies),
            'earningsTbd': sum(not c.get('next') for c in companies)}


def apply_views(data, research, fixed_clock, config=None, trading_days=None):
    today = as_date(fixed_clock)
    add_anchors(data['industries'], data['chokepoints'], data['companies'])
    internal = research.get('internal', {})
    data['meta']['weekly'] = weekly_view(research['weekly_rows'], data['industries'], data['chokepoints'], data['companies'], today, internal)
    days = trading_days if trading_days is not None else data['meta'].get('snapshot', {}).get('sourceAsOfByMarket', {})
    data['meta']['daily'] = daily_view(research['daily_rows'], data.get('indices', []), days,
                                      data['meta']['notion']['warnings'], (config or {}).get('daily'), internal)
    data['meta']['kpis'] = kpis(data['industries'], data['chokepoints'], data['companies'])
    data['meta']['notion']['warnings'].sort(key=lambda w: (w.get('table', ''), w.get('key', ''), w.get('field', ''), w['code']))
    return data


# Appendix E: safe Chinese diagnostics; never interpolate request or credential text.
CODE_TEXT = {'banned_words': '含禁用词「{词}」，该内容不显示',
 'banned_words_in_output': '页面里出现禁用词「{词}」（{位置}）',
 'company_cap_exceeded': '公司超过 80 家，多出的不显示',
 'contract_invalid': '契约文件不合法：{原因}',
 'cp_industry_mismatch': '所属卡点不属于该公司的行业，不挂卡点',
 'daily_duplicate': '同一市场同一天有多条，用最近编辑的一条',
 'daily_future_date': '日期晚于该市场最近交易日，已忽略',
 'duplicate_key': '与另一行重复：{key}（保留较早创建的一行）',
 'earnings_confirmed_without_source': '标了官方确认但没有 https 来源，按预估显示',
 'earnings_date_past': '下次财报日已过，待更新',
 'expired': '研判已过期（有效至 {日期}）',
 'financial_duplicate': '同一期有多条财报记录，保留录入日较晚的一条',
 'flash_date_future': '快讯日期晚于今天，按今天处理',
 'future_judgment_date': '研判日期晚于今天',
 'invalid_enum': '{列名}的选项「{值}」不在约定范围内',
 'legacy_data': '旧版数据，无研判信息',
 'list_truncated': '条目过多，只保留前 {上限} 条',
 'missing_dates': '缺研判日期或有效至',
 'missing_reason': '缺研判理由',
 'missing_required': '缺必填项：{列名}',
 'missing_source': '缺来源链接',
 'no_last_good': '读不到研究数据，也没有上次成功的版本',
 'no_weekly_row': '本周还没有主线研判',
 'not_current_week': '不是本周的研判，显示上次结论',
 'notion_bad_json': 'Notion 返回的内容无法解析',
 'notion_body_too_large': '单次响应超过 8 MB，已停止读取',
 'notion_cursor_loop': '分页游标重复，已停止读取',
 'notion_forbidden': 'NOTION_TOKEN 权限不足（403）',
 'notion_http_error': 'Notion 请求失败（{状态码}）',
 'notion_not_found': '{表}库 404：未共享给 connection 或已移动',
 'notion_rate_limited': 'Notion 限流（429），重试 3 次仍失败',
 'notion_schema_changed': 'Notion 列名被改：{列名}（`missing`）／Notion 列类型被改：{列名}（{原类型} → {新类型}）',
 'notion_server_error': 'Notion 服务器错误（{状态码}），重试 3 次仍失败',
 'notion_timeout': '读取超时或连接失败',
 'notion_token_missing': '未设置 NOTION_TOKEN',
 'notion_too_many_pages': '超过 50 页，已停止读取',
 'notion_unauthorized': 'NOTION_TOKEN 无效或无权限（401）',
 'number_not_integer': '{列名}应为整数',
 'number_out_of_range': '{列名}超出 {最小}–{最大}',
 'pct_maybe_fraction': '{列名}可能写成了小数（{值}），照原值显示',
 'pct_out_of_range': '{列名}超出合理范围，已置空',
 'pct_suspicious': '{列名}数值异常大，照常显示',
 'period_after_publish': '期末日晚于发布日',
 'prediction_words': '含预测性用词「{词}」，改用自动生成句',
 'publish_in_future': '发布日晚于今天',
 'quotes_coverage_low': '有行情的公司只有 {n}/{总数}（低于 70%）',
 'regex_mismatch': '{列名}格式不对：{值}',
 'relation_missing': '{列名}没有关联，或关联的行已停用',
 'relation_multiple': '{列名}只能关联 1 行',
 'relation_truncated': '关联过多，只保留前 {上限} 个',
 'row_quarantined': '本行数据有误，显示上次成功读取的版本',
 'table_quality_low': '有误的行太多（{坏行}/{总行}）',
 'text_long': '文字偏长：{n} 字（建议 ≤ {上限}）',
 'text_truncated': '文字超长，已截到 {上限} 字',
 'timezone_invalid': '时区无效：{值}，改用市场默认时区',
 'token_unknown_company': '财报日标记里的代号 {代号} 不存在或已停用，显示为「日期待定」',
 'url_invalid': '链接不是 https，已忽略',
 'validity_too_long': '有效期超过 14 天'}
