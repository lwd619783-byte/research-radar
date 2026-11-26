"""Local, read-only 17:30 disclosures and dated catalysts. All amounts retain source units."""
import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
from html import unescape
from html.parser import HTMLParser
from http.client import HTTPException
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata

from .market import symbol

EM = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
THS = 'https://stock.10jqka.com.cn/gushiyuce/'
CNINFO = 'https://www.cninfo.com.cn/new/hisAnnouncement/query'
BJ = timezone(timedelta(hours=8))
CATALYST_WINDOW_DAYS = 45
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


def _notice_rows(day, http, keyword, start, warnings):
    notices, seen = [], set()
    received, expected = 0, None
    headers = {'Referer': 'https://www.cninfo.com.cn/new/disclosure', 'Origin': 'https://www.cninfo.com.cn'}
    cutoff = datetime(day.year, day.month, day.day, 20, 30, tzinfo=BJ)
    for page in range(1, 13):
        try:
            payload = http.post_form_json(CNINFO, dict(tabName='fulltext', column='szse', stock='',
                plate='', secid='', category='', trade='', searchkey=keyword, sortName='time',
                sortType='desc', seDate=f'{start}~{day}', pageNum=page, pageSize=30, isHLtitle='true'),
                headers=headers)
            if not isinstance(payload, dict) or 'announcements' not in payload:
                raise ValueError('invalid announcement response')
            total = payload.get('totalAnnouncement')
            if total is not None:
                total = int(total)
            if not isinstance(payload['announcements'], list) and not (
                    payload['announcements'] is None and total == 0):
                raise ValueError('invalid announcement list')
            if expected is not None and total != expected:
                raise ValueError('announcement total changed')
            expected = total
        except (OSError, HTTPException, TypeError, ValueError):
            if page == 1 or warnings is None:
                raise
            break
        records = payload.get('announcements') or []
        received += len(records)
        for row in records:
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
            if not ident or ident in seen or not start <= published.date() <= day or published > cutoff:
                continue
            if keyword not in title:
                continue
            seen.add(ident)
            notices.append(dict(when=published, ident=ident, title=title, code=text(row.get('secCode')),
                                name=text(row.get('secName')), path=text(row.get('adjunctUrl'))))
        if total is not None and page * 30 >= total:
            if received != total:
                break
            return notices
        if total is None and payload.get('hasMore') is not True:
            return notices
    if warnings is None:
        raise ValueError('incomplete announcement list')
    warnings.append('巨潮' + keyword + '公告分页未完整')
    return notices


PLAN_UPDATE = re.compile('终止|取消|撤回|撤销|届满|结束|完成|完毕|结果|更正|变更|调整|延期|补充|进展')
PLAN_TITLE = re.compile('预披露|减持.*计划|计划.*减持|拟减持')
DATE_PART = r'(20\d{2}年\d{1,2}月\d{1,2}日)'
# An absolute range immediately following the plan's own timing field. A relative
# notice period, a historical trade, and a restricted-trading period are distinct.
PLAN_RANGE = re.compile(
    r'(?:减持期间|减持时间区间|减持时间|拟减持区间|计划减持区间|变动区间)'
    r'[:为]?(?:自(?:本次|本)?(?:减持计划公告|预披露公告|公告|减持计划)(?:披露|发布)?之?日'
    r'起?(?:\d+|十五)个交易日后的?(?:\d+|三)个月内(?:进行)?[,.(]*(?:即为|即从|即)?[(]?)?'
    r'(?:为|从|自)?' + DATE_PART + r'(?:起)?(?:至|到|~|—|－|-)' + DATE_PART)
PLAN_DATES = re.compile(r'拟减持(?:起始|开始)日期(?:为|:)'
                        + DATE_PART + r'[,，、](?:拟)?减持(?:结束|截止)日期(?:为|:)' + DATE_PART)
PLAN_INTENT = re.compile(r'(?:计划|拟)(?:自|于|在)' + DATE_PART + r'(?:起)?至' + DATE_PART
                         + r'(?:内|止|期间)?(?:以|通过|采用)(?:集中竞价|大宗交易|竞价交易|和|或|、|/|方式){1,15}减持')
SUSPEND_DATE = re.compile(r'(?:本公司|公司)股票(?:将)?(?:于|自)' + DATE_PART
                          + r'(?:[（(]星期[一二三四五六日][）)])?(?:开市|开盘)?(?:起)?(停牌|复牌)')


def _notice_windows(notice, body, day, keyword):
    """Extract dates only from the issuer's prospective, explicitly dated wording."""
    body = re.sub(r'\s+', '', unicodedata.normalize('NFKC', body))
    patterns = (PLAN_RANGE, PLAN_DATES, PLAN_INTENT) if keyword == '减持' else (SUSPEND_DATE,)
    windows, explicit_dates = [], False
    for pattern in patterns:
        for match in pattern.finditer(body):
            before = re.split(r'[。；;]', body[max(0, match.start()-50):match.start()])[-1]
            if re.search('此前|前次|上次|追溯|曾于|不减持|禁止|不得|若|如果|预计|可能|尚待|拟申请', before):
                continue
            try:
                begin = datetime.strptime(match[1], '%Y年%m月%d日').date()
                end = datetime.strptime(match[2], '%Y年%m月%d日').date() if keyword == '减持' else begin
            except ValueError:
                continue
            if end < begin:
                continue
            explicit_dates = True
            if not day < begin <= day + timedelta(days=5):
                continue
            label = '减持计划窗口' if keyword == '减持' else '异常波动' + match[2] + '安排'
            schedule = f'原公告拟减持期间 {begin} 至 {end}' if keyword == '减持' else f'原公告明确 {begin} {match[2]}'
            item = dict(title=label, detail=f"{notice['name']}（{notice['code']}），{schedule}。"
                        f"披露日 {notice['when'].date()}，巨潮公告编号 {notice['ident']}。")
            if item not in windows:
                windows.append(item)
    return windows, explicit_dates


def _notice_pdf(http, notice):
    # Only fetch dated CNINFO attachment paths belonging to this notice.
    ident = notice['ident']
    if not ident.isascii() or not ident.isdigit() or not re.fullmatch(
            r'finalpage/20\d{2}-\d{2}-\d{2}/' + re.escape(ident) + r'\.pdf', notice['path'], re.I):
        raise ValueError('invalid notice attachment')
    from pypdf import PdfReader
    data = http.get_bytes('https://static.cninfo.com.cn/' + notice['path'])
    if not data.startswith(b'%PDF-'):
        raise ValueError('invalid notice PDF')
    reader = PdfReader(BytesIO(data))
    return '\n'.join((page.extract_text() or '') for page in reader.pages[:6])


def _same_day_notices(notices, day, keyword):
    items = []
    for n in notices:
        if n['when'].date() != day:
            continue
        label = keyword + '公告'
        if keyword == '减持' and (PLAN_UPDATE.search(n['title']) or re.search('不减持|未减持', n['title'])):
            if not symbol(n['code']):
                continue
            label = '减持计划变更公告'
        subject = n['name'] + (f"（{n['code']}）" if symbol(n['code']) else '')
        items.append(dict(title=label, detail=f"{day} {subject}：{n['title']}。巨潮公告编号 {n['ident']}。"))
    return items


def disclosures(day, http, keyword, warnings=None):
    return _same_day_notices(_notice_rows(day, http, keyword, day, warnings), day, keyword)


def collect_disclosure_risks(day, http, *, recent_only=False):
    """At final review refresh today's announcements only. Historical PDFs belong to the earlier pass."""
    warnings, today, upcoming = [], [], []
    deadline = time.monotonic() + 180
    for keyword, lookback, doc_limit in (('减持', 35, 48), ('异常波动', 5, 8)):
        start = day if recent_only else day - timedelta(days=lookback)
        try:
            records = _notice_rows(day, http, keyword, start, warnings)
        except (OSError, HTTPException, TypeError, ValueError):
            warnings.append('巨潮' + keyword + '暂缺')
            continue
        today.extend(_same_day_notices(records, day, keyword))
        if recent_only:
            continue
        # A later correction/result can supersede an earlier plan. Without a
        # shareholder identifier, suppress the earlier plan for the entire issuer.
        updates = {}
        for n in records:
            if PLAN_UPDATE.search(n['title']) or re.search('不减持|未减持', n['title']):
                updates[n['code']] = max(updates.get(n['code'], n['when']), n['when'])
        # Failed pagination cannot establish the absence of later amendments.
        if '巨潮' + keyword + '公告分页未完整' in warnings:
            continue
        candidates = [n for n in records if symbol(n['code']) and
                      (n['code'] not in updates or n['when'] > updates[n['code']]) and
                      (PLAN_TITLE.search(n['title']) if keyword == '减持' else re.search('停牌|复牌', n['title']))]
        if len(candidates) > doc_limit:
            warnings.append('巨潮' + keyword + '原公告查验数量未覆盖全部候选')
        for n in candidates[:doc_limit]:
            if time.monotonic() >= deadline:
                warnings.append('巨潮' + keyword + '原公告核对时限内未完成')
                break
            try:
                body = _notice_pdf(http, n)
            except ImportError:
                warnings.append('巨潮计划日期核对缺少本机 PDF 读取组件')
                break
            except Exception:
                warnings.append('巨潮' + keyword + '部分公告原文暂缺')
                continue
            if not body.strip():
                warnings.append('巨潮' + keyword + '部分公告原文不可读')
                continue
            windows, explicit_dates = _notice_windows(n, body, day, keyword)
            upcoming.extend(windows)
            if not explicit_dates:
                warnings.append('巨潮' + keyword + '部分公告未核到明确计划日期')
    return upcoming + today, list(dict.fromkeys(warnings))


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
    end = day + timedelta(days=CATALYST_WINDOW_DAYS)
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


def jin10_events(day, http, *, coverage=None):
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
    dates = []
    for row in payload['data']:
        title, stamp, stars = text(row.get('title')), text(row.get('pub_time')), row.get('star')
        eligible = type(stars) is int and stars in (3, 4, 5) and title.startswith(('美国', '中国'))
        try:
            moment = datetime.fromisoformat(stamp)
            moment = moment.replace(tzinfo=BJ) if moment.tzinfo is None else moment.astimezone(BJ)
        except (ValueError, OverflowError):
            if eligible:
                raise
            continue
        dates.append(moment.date())
        if not eligible or (moment.date() == day and moment.strftime('%H:%M') <= '20:30'):
            continue
        events.append(dict(when=moment.date(), title=title, mapping='宏观流动性', category='macro',
                           stars=stars, focus=moment.strftime('北京时间 %Y-%m-%d %H:%M 公布'), source='金十财经日历'))
    if coverage is not None:
        end = day + timedelta(days=CATALYST_WINDOW_DAYS)
        forward_rows = sum(day <= row['when'] <= end for row in events)
        first, last = min(dates, default=None), max(dates, default=None)
        if not last:
            status = 'no_dated_evidence'
        elif last < day:
            status = 'past_only'
        elif forward_rows:
            status = 'forward_events'
        else:
            status = 'no_forward_evidence'
        coverage.update(status=status, inputRows=len(payload['data']), datedRows=len(dates),
                        firstObservedDate=first.isoformat() if first else None,
                        lastObservedDate=last.isoformat() if last else None,
                        eligibleForwardRows=forward_rows)
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
        if not d or not day <= d <= day + timedelta(days=CATALYST_WINDOW_DAYS):
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
    disclosure_items, disclosure_warnings = collect_disclosure_risks(day, http)
    mines.extend(disclosure_items)
    warnings.extend(disclosure_warnings)
    raw = []
    for name, read in (('东财会议', em_events), ('同花顺日历', ths_events)):
        raw.extend(attempt(name, lambda: read(day, http), []))
    coverage = dict(status='unavailable', inputRows=None, datedRows=None,
                    firstObservedDate=None, lastObservedDate=None, eligibleForwardRows=None)
    raw.extend(attempt('金十日历', lambda: jin10_events(day, http, coverage=coverage), []))
    coverage_warning = {
        'past_only': '金十日历输入日期均早于目标日，前瞻日程待核',
        'no_forward_evidence': '金十日历本次输入未提供定稿后45日窗口内可纳入的中美3至5星日程',
        'no_dated_evidence': '金十日历本次输入未含可核日期，前瞻日程待核',
    }.get(coverage['status'])
    if coverage_warning:
        warnings.append(coverage_warning)
    return dict(dragonTiger=lhb, mines=mines[:128], events=catalysts(day, raw, market)[:128],
                warnings=list(dict.fromkeys(warnings)), jin10Coverage=coverage)
