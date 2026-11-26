"""Derive the evening replay from dated observations. Percentage inputs are fractions."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
import math
import re

from market_calendar import calendar_data, is_session, known_non_session
from short_term_merge import contract, sanitize_short_term_text
from .market import symbol, tradable_name


def _number(x):
    return type(x) in (int, float) and abs(x) <= 2**53 and math.isfinite(x)


def _count(x):
    return x if type(x) is int and x >= 0 else None


def _pct(x):
    return f'{x * 100:+.2f}%' if _number(x) else '—'


def _money(x):
    return f'{x / 1e8:,.2f} 亿' if _number(x) else '—'


def _code(value):
    match = re.fullmatch(r'(?:(SH|SZ|BJ))?(\d{6})(?:\.(SH|SS|SZ|BJ))?', str(value).upper())
    if not match:
        return None
    canonical = symbol(match[2])
    if not canonical:
        return None
    exchange = canonical[-2:]
    if any(m and ('SH' if m == 'SS' else m) != exchange for m in (match[1], match[3])):
        return None
    return match[2]



def _previous_session(day):
    spec = calendar_data()['exchanges']['XSHG']
    prior = day - timedelta(days=1)
    while not is_session(spec, prior):
        prior -= timedelta(days=1)
    return prior


def _rows(raw, key, day):
    rows = raw.get(key)
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get('date', day.isoformat()) == day.isoformat()]


def _market_stock(row, day):
    if not tradable_name(row['name']):
        return False
    try:
        listed = date.fromisoformat(row.get('listed') or row.get('listedBefore'))
    except (TypeError, ValueError):
        return False
    return (day - listed).days >= 30 and _number(row.get('amount')) and row['amount'] >= 1_000_000_000


def _valid_quote(row):
    return (isinstance(row.get('name'), str) and bool(row['name'].strip()) and
            isinstance(row.get('code'), str) and bool(row['code'].strip()) and _number(row.get('pct')))


def dated_stock_quotes(raw, day):
    """Return unique dated observations and whether all three exchanges are complete.

    The batch date can bind undated rows. A contradictory row date, malformed
    quote or duplicate instrument invalidates the full-universe coverage claim.
    Conflicting observations also remove that instrument from the core pool.
    """
    if raw.get('date') != day.isoformat() or not isinstance(raw.get('stocks'), list):
        return [], False
    complete = raw.get('marketComplete', raw.get('universeComplete')) is True
    quotes, conflicts = {}, set()
    for row in raw['stocks']:
        if (not isinstance(row, dict) or row.get('date', day.isoformat()) != day.isoformat() or
                not _valid_quote(row) or not (key := _code(row['code'])) or
                ('price' in row and (not _number(row['price']) or row['price'] <= 0))):
            complete = False
            continue
        if key in quotes:
            complete = False
            if any(row.get(k) != quotes[key].get(k) for k in ('name', 'pct', 'amount', 'price')):
                conflicts.add(key)
        else:
            quotes[key] = row
    return [r for key, r in quotes.items() if key not in conflicts], bool(complete and quotes)


def _rank(quotes, links, reason):
    def display(row, position):
        spark = row.get('spark')
        spark = spark[-5:] if isinstance(spark, list) and all(_number(v) and v > 0 for v in spark) else []
        turnover = _money(row.get('amount'))
        if _number(row.get('turnoverRate')):
            turnover += f" · 换手 {row['turnoverRate'] * 100:.2f}%"
        return {'rank': position, 'code': row['code'], 'name': row['name'], 'pct': row['pct'],
                'turnover': turnover, 'spark': spark, 'radarLink': links.get(row['code']),
                'netFlow': _money(row['netFlow']) if _number(row.get('netFlow')) else None,
                'px': f"{row['price']:.2f}" if _number(row.get('price')) else None,
                'reason': row.get('reason') or reason}
    # No gainers (or decliners) means an empty side, even on a one-sided market.
    result = {}
    for side, sign in (('up', 1), ('down', -1)):
        selected = sorted((r for r in quotes if r['pct'] * sign > 0),
                          key=lambda r: (-r['pct'] * sign, r['code']))
        result[side] = [display(r, pos) for pos, r in enumerate(selected[:5], 1)]
    return result


@dataclass
class BoardMatch:
    industry: str | None
    score: int | None
    points: dict[str, str]
    ambiguous: bool

    def star_label(self):
        if self.score is None or self.score < 16:
            return None
        names = [name for name, ind in self.points.items() if ind == self.industry]
        if names:
            return f'{self.industry} · {self.score}/20 · 卡点：' + '、'.join(sorted(names))
        return None


def _has_term(term, labels):
    if not isinstance(term, str) or len(term.strip()) < 2:
        return False
    if term.isascii():
        pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
        return any(re.search(pattern, label, re.I) for label in labels)
    return any(term.casefold() in label.casefold() for label in labels)


def _radar_links(boards, radar, companies):
    industries = {r['name']: r for r in radar.get('industries', []) if r.get('name')}
    points = {p['name']: p for p in radar.get('chokepoints', [])
              if isinstance(p.get('name'), str) and p.get('ind') in industries}
    linked = {}
    for row in boards:
        labels = [row['name'], *(s for s in row.get('keywords', []) if isinstance(s, str))]
        candidates = {n for n in industries if n == row['name'] or _has_term(n, labels)}
        hits = {}
        for name, point in points.items():
            segments = re.split(r'[、/，,；;]', point.get('seg') or '')
            if any(_has_term(term.strip(), labels) for term in [name, *segments]):
                hits[name] = point['ind']
        candidates.update(hits.values())
        member_ids = {_code(code) or str(code) for code in row.get('constituents', [])}
        members = [companies.get(code) for code in member_ids]
        if not candidates and row.get('constituentsComplete', True):
            votes = Counter(m['ind'] for m in members if m and m.get('ind') in industries)
            if votes:
                winner, count = votes.most_common(1)[0]
                if count > len(members) / 2:
                    candidates.add(winner)
        for company in members:
            if company and (point := points.get(company.get('cp'))) and point['ind'] == company.get('ind'):
                hits[point['name']] = point['ind']
        industry = next(iter(candidates)) if len(candidates) == 1 else None
        score = industries.get(industry, {}).get('total')
        unresolved = len(candidates) > 1 or (not industry and any(m and m.get('ind') in industries for m in members))
        linked[row['code']] = BoardMatch(industry, score if type(score) is int and 0 <= score <= 20 else None,
                                         hits, unresolved)
    return linked


def _matrix(boards, linked, radar):
    rules = [('q-res', '主线共振', 'ai', '高分行业上涨'), ('q-pulse', '纯情绪脉冲', 'stale', '短线活跃'),
             ('q-dip', '主线分歧', 'auto', '高分行业回调'), ('q-kill', '双杀回避', 'conflict', '弱势观察')]
    quadrants = {k: dict(key=k, title=title, badge='st ' + tone, badgeText=label, items=[])
                 for k, title, tone, label in rules}
    if radar.get('industries'):
        for row in sorted(boards, key=lambda r: (-abs(r['pct']), r['code'])):
            match = linked[row['code']]
            if match.ambiguous or (match.industry and match.score is None):
                continue
            high = match.score is not None and match.score >= 16
            change = row['pct']
            if change >= .02:
                key = 'q-res' if high else 'q-pulse'
            elif high and change < 0:
                key = 'q-dip'
            elif radar.get('chokepoints') and not match.points and change <= -.02:
                key = 'q-kill'
            else:
                continue
            if len(quadrants[key]['items']) < 5:
                text = f'{match.industry} · {match.score}/20 分' if match.industry else '未匹配雷达行业'
                note = '未命中雷达卡点' if key == 'q-kill' else '依行业评分及当日涨跌划分'
                quadrants[key]['items'].append(dict(name=row['name'], meta=f'{text} · {_pct(change)}',
                                                     note=note))
    return list(quadrants.values())


def _pool(raw, key, day):
    if not isinstance(raw.get(key), list):
        return None
    entries = _rows(raw, key, day)
    if len(entries) != len(raw[key]):
        return None
    pool = {}
    for row in entries:
        symbol, height = _code(row.get('code')), row.get('height')
        if not symbol or type(height) is not int or height < 1 or symbol in pool:
            return None
        pool[symbol] = row
    return pool


def _cycle(current, previous, broken):
    steps = contract()['day_entry_contract']['cycle_steps_fixed']
    height = max((r['height'] for r in current.values()), default=0) if current is not None else None
    result = dict(steps=steps, activeStep=None, maxHeight=f'{height} 板' if height is not None else '—',
                  note='连板股池或晋级数据暂缺', tiers=[])
    if current is None or previous is None:
        return result, height
    result['tiers'] = []
    all_winners = 0
    for base, title in ((1, '1进2'), (2, '2进3'), (3, '3进4及以上')):
        cohort = {k: r for k, r in previous.items() if r['height'] == base or (base == 3 and r['height'] > 3)}
        winners = [current[k] for k, r in cohort.items()
                   if k in current and current[k]['height'] == r['height'] + 1]
        winners.sort(key=lambda r: (-r['height'], r['code']))
        all_winners += len(winners)
        rate = f'{len(winners)}/{len(cohort)} ({len(winners)/len(cohort):.0%})' if cohort else '—'
        result['tiers'].append(dict(tier=title, rate=rate, stocks=[
            dict(n=r.get('name') or r['code'], c=_pct(r.get('pct')), tag=f"{r['height']}板") for r in winners[:5]]))
    if previous and _number(broken) and 0 <= broken <= 1:
        promoted = all_winners / len(previous)
        if promoted < .10 and broken >= .40:
            step = 0
        elif promoted < .20 and broken >= .30:
            step = 4
        elif height >= 3 and promoted >= .35 and broken <= .25:
            step = 2
        elif height >= 3 and (broken > .25 or promoted < .35):
            step = 3
        else:
            step = 1
        result.update(activeStep=step, note=f'昨日封板股今日晋级 {promoted:.1%}，今日炸板率 {broken:.1%}。')
    return result, height


def _anchors(metrics, leader):
    turnover = metrics.get('turnoverCny')
    if _number(turnover) and turnover > 0:
        first = ('下一交易日成交额能否守住今日水平', [('turnoverCny', turnover)])
    else:
        first = ('下一交易日成交额能否环比持平或增加', [('turnoverDeltaCny', 0)])
    second = ('上涨家数能否不少于下跌家数，涨停家数能否不少于跌停家数',
              [('advanceBalance', 0), ('limitBalance', 0)])
    third_checks, third_title = [], []
    if leader:
        third_checks.append(('board:' + leader['code'], 0))
        third_title.append(leader['name'] + '能否保持平盘或上涨')
    height = metrics.get('maxHeight')
    floor = max(2, height) if isinstance(height, int) else 2
    third_checks.append(('maxHeight', floor))
    third_title.append(f'能否出现 {floor} 板及以上个股')
    result = []
    for i, (title, checks) in enumerate([first, second, ('，'.join(third_title), third_checks)], 1):
        rules = [dict(metric=metric, minimum=floor) for metric, floor in checks]
        desc = ('基准成交额 ' + _money(turnover)) if i == 1 and _number(turnover) else '按下一交易日收盘观测逐项对照。'
        result.append(dict(code=f'ANCHOR {i:02}', title=title, desc=desc, rule=dict(claim=title, checks=rules)))
    return result


def reconcile_previous_day(previous, day, metrics):
    prior = _previous_session(day).isoformat()
    if not previous or previous.get('date') != prior:
        message = '首个记录日，暂无前日对比' if not previous else '上一交易日快照暂缺'
        return dict(targetDate=prior, summary=message, items=[])
    items = []
    pending = []
    for anchor in previous.get('anchors', [])[:3]:
        rule = anchor.get('rule') or {}
        checks = rule.get('checks') or []
        if rule.get('claim') != anchor.get('title') or not checks:
            pending.append(anchor['code'])
            continue
        tested, observations = [], []
        for check in checks:
            key, minimum = check.get('metric'), check.get('minimum')
            value = metrics.get(key)
            if not _number(value) or not _number(minimum):
                break
            tested.append(value >= minimum)
            if key.startswith('board:'):
                observations.append(f'{key[6:]} 涨跌 {_pct(value)}，门槛 {_pct(minimum)}')
            elif key in ('turnoverCny', 'turnoverDeltaCny'):
                observations.append(f'成交额{"环比变化" if "Delta" in key else ""} {_money(value)}，门槛 {_money(minimum)}')
            else:
                label = {'maxHeight': '最高连板', 'advanceBalance': '上涨减下跌家数', 'limitBalance': '涨停减跌停家数'}.get(key, key)
                observations.append(f'{label} {value:g}，门槛 {minimum:g}')
        if len(tested) != len(checks):
            pending.append(anchor['code'])
            continue
        status = 'pass' if all(tested) else 'partial' if any(tested) else 'fail'
        items.append(dict(code=anchor['code'], claim=anchor['title'], status=status,
                          statusLabel={'pass': '达到', 'partial': '部分达到', 'fail': '未达到'}[status],
                          actual='；'.join(observations)))
    summary = f'上一交易日有 {len(items)} 条锚点可按收盘数据对照。'
    if pending:
        summary += ' ' + '、'.join(pending) + ' 缺少量化条件或当日观测。'
    return dict(targetDate=prior, summary=summary, items=items)


def _board_switches(previous, current, previous_time):
    details = []
    for group, values in current.items():
        prior = previous.get(group, {})
        if len(values) < 2 or values.keys() != prior.keys() or None in (*values.values(), *prior.values()):
            continue
        changes = []
        for sign, label in ((1, '领涨'), (-1, '领跌')):
            leaders = []
            for snapshot in (prior, values):
                extreme = max(sign * pct for pct in snapshot.values())
                names = [name for (_, name), pct in snapshot.items() if sign * pct == extreme]
                if extreme > 0 and len(names) == 1:
                    leaders.append(names[0])
            if len(leaders) == 2 and leaders[0] != leaders[1]:
                changes.append(f'{label}由{leaders[0]}转为{leaders[1]}')
        if changes:
            details.append(f'相较 {previous_time}，同组 {len(values)} 个{group[0]}样本中' + '，'.join(changes))
    return details


def _timeline(raw, day, breadth, dragon, ego, board_sets):
    bars = _rows(raw, 'intraday', day)
    board_kinds = {}
    for key, label in [('industries', '行业'), ('concepts', '概念')]:
        for row in board_sets[key]:
            board_kinds.setdefault((row['code'], row['name']), set()).add(label)
    result = []
    previous, previous_time = {}, None
    for time, label in [('09:25', '集合竞价'), ('10:30', '早盘'), ('13:30', '午后'), ('15:00', '收盘')]:
        ticks = [r for r in bars if r.get('time') == time and r.get('name') and _number(r.get('pct'))
                 and (time != '09:25' or (r.get('auctionConfirmed') is True and r.get('date') == day.isoformat()))]
        details = [f"{r['name']} {_pct(r['pct'])}" for r in ticks[:6]]
        groups = {}
        methods, ambiguous = {}, set()
        for tick in ticks:
            board = tick.get('code'), tick['name']
            kinds = board_kinds.get(board, set())
            if len(kinds) != 1:
                continue
            kind = next(iter(kinds))
            method = (tick.get('source'), tick.get('basis'), tick.get('interval'))
            if (tick.get('date') != day.isoformat() or
                    not all(isinstance(v,str) and v.strip() for v in method) or
                    methods.setdefault(kind, method) != method):
                ambiguous.add(kind)
                continue
            group = (kind, *method)
            values = groups.setdefault(group, {})
            if values.setdefault(board, tick['pct']) != tick['pct']:
                values[board] = None
        groups = {g:v for g,v in groups.items() if g[0] not in ambiguous}
        details.extend(_board_switches(previous, groups, previous_time))
        previous, previous_time = groups, time
        if time == '15:00':
            if breadth['turnover'] != '—':
                details.append('成交额 ' + breadth['turnover'])
            result.append(dict(time=time, phase=label, title='收盘行情', detail='；'.join(details) or '收盘汇总暂缺',
                               tag='盘后记录'))
        elif details:
            result.append(dict(time=time, phase=label, title='时点涨跌幅', detail='；'.join(details), tag='分时记录'))
    for time, phase, title, detail in [
        ('17:30', '盘后栏目', '龙虎榜席位与公告', dragon.get('summary') or '龙虎榜数据暂缺'),
        ('20:15', '晚间栏目', '散户舆情样本', ego.get('summary') or '舆情样本暂缺')]:
        result.append(dict(time=time, phase=phase, title=title, detail=detail, tag='盘后记录'))
    return result


def _public_text(value):
    if isinstance(value, str):
        return sanitize_short_term_text(value)
    if isinstance(value, list):
        return [_public_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _public_text(item) for key, item in value.items()}
    return value


def build_day(day: date, raw: dict, radar: dict, previous: dict | None) -> dict:
    """No network or I/O except locally owned contracts and session calendar."""
    day_id = day.isoformat()
    if raw.get('date') != day_id or day.weekday() >= 5 or known_non_session('000001.SS', day_id):
        raise ValueError('requested trading day does not match the observations')
    stocks, complete = dated_stock_quotes(raw, day)
    b = dict(raw.get('breadth') or {})
    if not complete:
        for key in ('up', 'flat', 'down', 'turnoverCny', 'turnoverDeltaCny'):
            b.pop(key, None)
    prior_day = _previous_session(day)
    prior_total = (previous or {}).get('observedTotals', {}).get('turnoverCny')
    if (complete and _number(b.get('turnoverCny')) and not _number(b.get('turnoverDeltaCny')) and
            previous and previous.get('date') == prior_day.isoformat() and _number(prior_total)):
        b['turnoverDeltaCny'] = b['turnoverCny'] - prior_total
    breadth = {k: _count(b.get(k)) for k in ('up', 'flat', 'down', 'limitUp', 'limitDown')}
    breadth.update(turnover=_money(b.get('turnoverCny')), turnoverDelta=_money(b.get('turnoverDeltaCny')),
                   brokenRate=f"{b['brokenRate']:.1%}" if _number(b.get('brokenRate')) and 0 <= b['brokenRate'] <= 1 else '—',
                   yesterdayPremium=_pct(b.get('yesterdayPremium')))
    companies = {_code(c.get('sym') or c.get('code')): c for c in radar.get('companies', [])
                 if c.get('market', c.get('mkt')) == 'A股' and _code(c.get('sym') or c.get('code'))}
    core = [r for r in stocks if _code(r['code']) in companies]
    company_links = {r['code']: companies[_code(r['code'])].get('ind') or '雷达核心池' for r in core}
    market = [r for r in stocks if complete and r.get('inMarketUniverse', True) and _market_stock(r, day)]
    board_sets = {k: [r for r in _rows(raw, k, day) if _valid_quote(r)] for k in ('industries', 'concepts')}
    boards = board_sets['industries'] + board_sets['concepts']
    linked = _radar_links(boards, radar, companies)
    board_links = {code: match.star_label() for code, match in linked.items()}
    groups = {k: _rank(rows, board_links, '行业/题材短线资金波动') for k, rows in board_sets.items()}
    leader = next(iter(groups['industries']['up']), None)
    current = _pool(raw, 'limitPool', day)
    cycle, height = _cycle(current, _pool(raw, 'previousLimitPool', prior_day), b.get('brokenRate'))
    metrics = {k: b.get(k) for k in ('turnoverCny', 'turnoverDeltaCny')}
    for metric, plus, minus in [('advanceBalance', 'up', 'down'), ('limitBalance', 'limitUp', 'limitDown')]:
        if breadth[plus] is not None and breadth[minus] is not None:
            metrics[metric] = breadth[plus] - breadth[minus]
    metrics.update({'board:' + r['code']: r['pct'] for r in boards})
    metrics['maxHeight'] = height
    dragon = raw.get('dragonTiger') or dict(summary='龙虎榜数据暂缺', items=[])
    ego = raw.get('ego') or dict(score=None, state='样本暂缺', summary='本次未取得舆情样本', platforms=[], posts=[])
    score = ego.get('score')
    theme = 'warn' if not _number(score) or 40 <= score < 65 else 'up' if score >= 65 else 'down'
    subtitle = f"{leader['name']}领涨行业，涨幅 {_pct(leader['pct'])}。" if leader else '领涨行业数据暂缺。'
    observed = {'turnoverCny': b['turnoverCny']} if _number(b.get('turnoverCny')) else {}
    result = dict(date=day_id, observedTotals=observed, shortDate=day.strftime('%m/%d'), weekday='周' + '一二三四五六日'[day.weekday()],
                  themeColor=theme, sentimentScore=score, sentimentState=ego.get('state') or '样本暂缺',
                  headline=f'{day.month} 月 {day.day} 日 A 股收盘复盘', subHeadline=subtitle, breadth=breadth,
                  pulse=dict(finalTime='交易日晚间汇总', quoteTime=day_id + (' 三市收盘汇总' if complete else ' 部分行情'),
                             egoTime=ego.get('summary') or '舆情样本暂缺', notionSync='本机快照'),
                  yesterdayReconcile=reconcile_previous_day(previous, day, metrics),
                  stocks=dict(market=_rank(market, company_links, '按当日收盘涨跌幅排序'),
                              radar=_rank(core, company_links, '雷达核心池收盘涨跌幅')),
                  cycle=cycle, matrix=_matrix(boards, linked, radar), dragonTiger=dragon,
                  ego=ego, anchors=_anchors(metrics, leader), timeline=_timeline(raw, day, breadth, dragon, ego, board_sets),
                  strategyPlan=dict(offense='观察领涨方向的次日延续情况。', defense='留意盘后公告及异动提示。',
                                    mines=raw.get('mines') or []), **groups)
    return _public_text(result)
