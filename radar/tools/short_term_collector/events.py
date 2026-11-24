"""Local, read-only 17:30 disclosures and dated catalysts. All amounts retain source units."""
import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import unicodedata

from .market import symbol

EM = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
THS = 'https://stock.10jqka.com.cn/gushiyuce/'
CNINFO = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
BJ = timezone(timedelta(hours=8))
UNLOCK_WAN = 10_000  # LIFT_MARKET_CAP is in ten-thousand CNY; the screen is >= 1亿.
CONFERENCE = re.compile('大会|峰会|博览会|展览会|交易会|发布会|开发者会议|行业会议|论坛')


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and not isinstance(value, bool) else None
    except (ValueError, TypeError):
        return None


def text(value):
    return ' '.join(unescape(re.sub(r'<[^>]{1,300}>', '', str(value or ''))).split())


def as_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def em_rows(http, report, filters, sort, order='1', *, columns='ALL'):
    query = dict(reportName=report, filter=filters, columns=columns, sortColumns=sort,
                 sortTypes=order, pageSize=500, source='WEB', client='WEB')
    rows = []
    for page in range(1, 13):
        payload = http.get_json(EM, {**query, 'pageNumber': page})
        if not isinstance(payload, dict) or payload.get('success') is False:
            raise ValueError('Eastmoney report unavailable')
        result = payload.get('result')
        if not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise ValueError('invalid report')
        rows.extend(row for row in result['data'] if isinstance(row, dict))
        if page >= int(result['pages']):
            return rows
    raise ValueError('incomplete paginated report')


def seat_summary(buys, sells):
    # Separate anonymous institutional seats can share an ID and name.
    # Multiset union keeps distinct amounts and counts cross-list repeats once.
    sides = []
    for records, side in ((buys, 'BUY'), (sells, 'SELL')):
        eligible = [r for r in records if number(r.get(side)) is not None]
        selected = sorted(eligible, key=lambda r: number(r[side]), reverse=True)[:5]
        counted = Counter()
        for r in selected:
            net = number(r.get('NET'))
            buy, sell = number(r.get('BUY')), number(r.get('SELL'))
            if net is None and buy is not None and sell is not None:
                net = buy - sell
            if net is None:
                raise ValueError('missing seat amount')
            counted[(text(r.get('OPERATEDEPT_CODE')), text(r.get('OPERATEDEPT_NAME')),
                     buy, sell, net)] += 1
        if not counted:
            raise ValueError('missing seat side')
        sides.append(counted)
    groups = Counter()
    for (code, name, _, _, net), memberships in (sides[0] | sides[1]).items():
        if '机构专用' in name or code == '0':
            group = '机构'
        elif '沪股通' in name or '深股通' in name:
            group = '沪深股通'
        elif '拉萨' in name and ('东方财富' in name or '东财' in name):
            group = '东财拉萨'
        else:
            group = '其他席位'
        groups[group] += memberships * net
    return ' · '.join(f'{group} {amt / 10000:+,.1f} 万元' for group, amt in groups.items())


def dragon(day, http, warnings):
    session = f"(TRADE_DATE='{day}')"
    rows = em_rows(http, 'RPT_DAILYBILLBOARD_DETAILSNEW', session, 'BILLBOARD_DEAL_AMT', '-1',
                   columns='SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLANATION,BILLBOARD_DEAL_AMT,BILLBOARD_NET_AMT')
    # A multi-session movement cannot be reported as a single session's cash.
    daily = [r for r in rows if as_date(r.get('TRADE_DATE')) == day and
             re.fullmatch(r'\d{6}', str(r.get('SECURITY_CODE', ''))) and symbol(r['SECURITY_CODE']) and r.get('EXPLANATION')
             and not re.search(r'连续|三个交易日|三日|期间', r['EXPLANATION'])
             and number(r.get('BILLBOARD_DEAL_AMT')) is not None]
    selected = {}
    for row in sorted(daily, key=lambda r: number(r['BILLBOARD_DEAL_AMT']), reverse=True):
        selected.setdefault(row['SECURITY_CODE'], row)
        if len(selected) == 5:
            break
    sides = {}
    if selected:
        codes = ','.join(f'"{code}"' for code in selected)
        condition = f'{session}(SECURITY_CODE in ({codes}))'
        try:
            for side in ('BUY', 'SELL'):
                records = em_rows(http, 'RPT_BILLBOARD_DAILYDETAILS' + side, condition, side, '-1',
                                  columns='SECURITY_CODE,TRADE_DATE,EXPLANATION,OPERATEDEPT_CODE,OPERATEDEPT_NAME,BUY,SELL,NET')
                sides[side] = {}
                for record in records:
                    code = record.get('SECURITY_CODE')
                    if code in selected and as_date(record.get('TRADE_DATE')) == day and (
                            record.get('EXPLANATION') == selected[code]['EXPLANATION']):
                        sides[side].setdefault(code, []).append(record)
        except (OSError, TypeError, ValueError, KeyError):
            sides.clear()
    items = []
    for code, row in selected.items():
        try:
            seats = seat_summary(sides['BUY'][code], sides['SELL'][code])
        except (OSError, TypeError, ValueError, KeyError):
            warnings.append('龙虎榜部分席位明细暂缺')
            seats = '当日同一上榜原因的买卖前五席明细暂缺'
        net = number(row.get('BILLBOARD_NET_AMT'))
        items.append(dict(stock=f"{text(row.get('SECURITY_NAME_ABBR'))} ({code})", tag='单日异动',
                          tone='stale' if net is None else 'up-tag' if net > 0 else 'down-tag',
                          net='净额暂缺' if net is None else f'全榜净额 {net / 1e8:+.2f} 亿元',
                          seats=seats, note=text(row['EXPLANATION'])))
    return dict(summary=f'{day} 按龙虎榜成交额列示单日异动，收录 {len(items)} 只。', items=items)


def unlocks(day, http):
    end = day + timedelta(days=5)
    filters = f"(FREE_DATE>'{day}')(FREE_DATE<='{end}')(LIFT_MARKET_CAP>={UNLOCK_WAN})"
    mines = []
    for row in em_rows(http, 'RPT_LIFT_STAGE', filters, 'LIFT_MARKET_CAP', '-1'):
        release, amount = as_date(row.get('FREE_DATE')), number(row.get('LIFT_MARKET_CAP'))
        if release and day < release <= end and amount is not None and amount >= UNLOCK_WAN:
            mines.append(dict(title='大额解禁', detail=f"{release} {text(row.get('SECURITY_NAME_ABBR'))}"
                              f"（{text(row.get('SECURITY_CODE'))}），参考解禁市值 {amount / 10000:.2f} 亿元。"))
    return mines


def disclosures(day, http, keyword, warnings=None):
    """A disclosure date is observable. The title is not a future execution date."""
    mines, seen = [], set()
    headers = {'Referer': 'https://www.cninfo.com.cn/new/disclosure', 'Origin': 'https://www.cninfo.com.cn'}
    cutoff = datetime(day.year, day.month, day.day, 20, 30, tzinfo=BJ)
    for page in range(1, 13):
        try:
            payload = http.post_form_json(CNINFO, dict(tabName='fulltext', column='szse', stock='',
                plate='', secid='', category='', trade='', searchkey=keyword, sortName='time',
                sortType='desc', seDate=f'{day}~{day}', pageNum=page, pageSize=30, isHLtitle='true'),
                headers=headers)
            if not isinstance(payload, dict) or 'announcements' not in payload:
                raise ValueError('invalid announcement response')
            total = payload.get('totalAnnouncement')
            if total is not None:
                total = int(total)
            if not isinstance(payload['announcements'], list) and not (
                    payload['announcements'] is None and total == 0):
                raise ValueError('invalid announcement list')
        except (OSError, TypeError, ValueError):
            if page == 1 or warnings is None:
                raise
            break
        for row in payload.get('announcements') or []:
            if not isinstance(row, dict):
                continue
            stamp = number(row.get('announcementTime'))
            if stamp is None:
                continue
            try:
                published = datetime.fromtimestamp(stamp / 1000, BJ)
            except (OverflowError, OSError, ValueError):
                continue
            ident, title = text(row.get('announcementId')), text(row.get('announcementTitle'))
            if not ident or ident in seen or published.date() != day or published > cutoff:
                continue
            if keyword not in title or (keyword == '减持' and
                    re.search('减持完毕|减持计划.*(?:届满|结束|完成)|不减持|未减持', title)):
                continue
            seen.add(ident)
            mines.append(dict(title=keyword + '公告', detail=f"{day} {text(row.get('secName'))}：{title}"))
        if total is not None and page * 30 >= total:
            return mines
        if total is None and payload.get('hasMore') is not True:
            return mines
    if warnings is None:
        raise ValueError('incomplete announcement list')
    warnings.append('巨潮' + keyword + '公告分页未完整')
    return mines


class THSCalendar(HTMLParser):
    """The public weekly calendar uses a row-spanned date and separate commentary rows."""
    def __init__(self):
        super().__init__()
        self.active = False
        self.cell = None
        self.cells = []
        self.rows = []
        self.when = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.active = 'tzrl' in dict(attrs).get('class', '').split()
        elif self.active and tag == 'tr':
            self.cells = []
        elif self.active and tag == 'td':
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag == 'table':
            self.active = False
        elif tag == 'td' and self.cell is not None:
            self.cells.append(text(' '.join(self.cell)))
            self.cell = None
        elif tag == 'tr':
            cells = self.cells
            if len(cells) == 3:
                self.when = as_date(cells[0])
                cells = cells[1:]
            if self.when and len(cells) == 2 and CONFERENCE.search(cells[0]):
                self.rows.append((self.when, cells[0], cells[1]))


def ths_events(day, http):
    parser = THSCalendar()
    source = http.get_text(THS, encoding='gb18030', headers={'Referer': 'https://www.10jqka.com.cn/'})
    if '投资日历' not in source or 'tzrl' not in source:
        raise ValueError('calendar unavailable')
    parser.feed(source)
    return [dict(when=d, title=t, mapping=m, focus='', category='industry',
                 stars=3, source='同花顺投资日历') for d, t, m in parser.rows]


def em_events(day, http):
    end = day + timedelta(days=45)
    rows = em_rows(http, 'RPT_CPH_FECALENDAR',
        f"(STD_TYPE_CODE=\"1\")(START_DATE>='{day}')(START_DATE<='{end}')", 'START_DATE')
    return [dict(when=as_date(r.get('START_DATE')), end=as_date(r.get('END_DATE')), title=text(r['FE_NAME']),
                 focus=text(r.get('CONTENT'))[:120], mapping='', category='industry',
                 stars=3, source='东方财富会议日历') for r in rows
            if str(r.get('STD_TYPE_CODE')) == '1' and CONFERENCE.search(text(r.get('FE_NAME')) + text(r.get('FE_TYPE')))]


async def _jin10_mcp(token):
    # Official read-only list_calendar returns the current natural week.
    # The optional dependency and credential remain local to the scheduled CLI.
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with asyncio.timeout(18), httpx.AsyncClient(
            headers={'Authorization': 'Bearer ' + token}, timeout=8) as client:
        async with streamable_http_client('https://mcp.jin10.com/mcp', http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool('list_calendar', {})
                if result.isError:
                    raise ValueError('calendar unavailable')
                return result.structuredContent or json.loads(result.content[0].text)


def jin10_events(day, http):
    path = os.environ.get('SHORT_TERM_JIN10_CALENDAR_FILE')
    token = os.environ.get('JIN10_MCP_TOKEN')
    if path:
        with Path(path).open('rb') as source:
            raw = source.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('calendar too large')
        payload = json.loads(raw)
    elif token:
        payload = asyncio.run(_jin10_mcp(token))
    else:
        raise ValueError('calendar not configured')
    if payload.get('status') != 200 or not isinstance(payload.get('data'), list):
        raise ValueError('invalid calendar')
    events = []
    for row in payload['data']:
        title, stamp, stars = text(row.get('title')), text(row.get('pub_time')), row.get('star')
        if type(stars) is not int or stars not in (3, 4, 5) or not title.startswith(('美国', '中国')):
            continue
        moment = datetime.fromisoformat(stamp)
        moment = moment.replace(tzinfo=BJ) if moment.tzinfo is None else moment.astimezone(BJ)
        if moment.date() == day and moment.strftime('%H:%M') <= '20:30':
            continue
        events.append(dict(when=moment.date(), title=title, mapping='宏观流动性', category='macro',
                           stars=stars, focus=moment.strftime('北京时间 %Y-%m-%d %H:%M 公布'), source='金十财经日历'))
    return events


def catalysts(day, raw, market):
    panels = []
    for name in ('industries', 'concepts'):
        boards = market.get(name) or []
        if isinstance(boards, dict):
            boards = boards.get('up', []) + boards.get('down', [])
        panels.extend(boards)
    events = {}
    for row in raw:
        d = row['when']
        if not d or not day <= d <= day + timedelta(days=45):
            continue
        title = row['title']
        short = re.split(r'将于|将定于|拟于|定于', title, maxsplit=1)[0].strip()
        key = d.isoformat(), re.sub(r'[\W_]', '', unicodedata.normalize('NFKC', short)).lower()
        if not key[1]:
            continue
        if key in events:
            if row.get('mapping') and not events[key].get('mapping'):
                events[key]['mapping'] = row['mapping']
            continue
        events[key] = row.copy()
    result = []
    for key, event in sorted(events.items()):
        start, title = event['when'], event['title']
        left = (start - day).days
        macro = event['category'] == 'macro'
        subject = ' '.join((title, event.get('mapping', ''), event.get('focus', '')))
        matched = [r for r in panels if r.get('name') and r['name'] in subject]
        mapping = event.get('mapping') or ' / '.join(dict.fromkeys(r['name'] for r in matched)) or '板块关联待补'
        returns = [(r['name'], number(r.get('fiveDayReturn'))) for r in matched]
        known = [(n, v) for n, v in returns if v is not None]
        if macro:
            stage, tone, note = '宏观定调锚', 'ai', '观察公布值及发布后市场变化。'
        elif known:
            board, change = max(known, key=lambda x: x[1])
            stage, tone = ('临近防兑现', 'stale') if left <= 3 and change >= .05 else ('会前预期观察', 'auto')
            note = f'{board} 已收盘五个交易日累计 {change:+.2%}，距离开始 {left} 天。'
        else:
            stage, tone, note = '会前预期观察', 'auto', '缺少对应板块五日涨幅，暂缺兑现判断。'
        end = event.get('end')
        date_label = start.isoformat() + (f' 至 {end}' if end and end > start else '')
        ident = hashlib.sha256('|'.join(key).encode()).hexdigest()[:20]
        result.append(dict(id='ev-' + ident, dateLabel=date_label, startDate=start.isoformat(),
            daysLeft=f'T-{left}天', stars=event['stars'], category=event['category'],
            categoryLabel='宏观数据' if macro else '产业会议', title=title[:160],
            focus=event.get('focus') or title[:120], mapping=mapping[:100], phaseTag=stage, phaseTone=tone,
            expectationNote=note, source=event['source']))
    return result


def collect_events(day, market, http):
    warnings = []

    def attempt(label, read, default):
        try:
            return read()
        except Exception:
            # Credentials, upstream bodies and SDK exceptions must remain local.
            warnings.append(label + '暂缺')
            return default

    lhb = attempt('龙虎榜', lambda: dragon(day, http, warnings), dict(summary='今日龙虎榜数据暂缺', items=[]))
    mines = attempt('解禁', lambda: unlocks(day, http), [])
    for term in ('减持', '异常波动'):
        mines.extend(attempt('巨潮' + term, lambda: disclosures(day, http, term, warnings), []))
    raw = []
    for name, read in (('东财会议', em_events), ('同花顺日历', ths_events), ('金十日历', jin10_events)):
        raw.extend(attempt(name, lambda: read(day, http), []))
    return dict(dragonTiger=lhb, mines=mines[:128], events=catalysts(day, raw, market)[:128],
                warnings=list(dict.fromkeys(warnings)))
