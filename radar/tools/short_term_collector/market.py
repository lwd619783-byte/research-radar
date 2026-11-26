"""Dated mainland cash-market observations for the local evening collector."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import math
import re
import time

from market_calendar import calendar_data, is_session

BJ = timezone(timedelta(hours=8))
CLIST = 'https://push2.eastmoney.com/api/qt/clist/get'
KLINE = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
ALL_A = 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048'
BEIJING = 'm:0 t:81 s:2048'
TARGET_TIMES = {'09:25', '10:30', '13:30', '15:00'}
RECOVERY_BATCH_SIZE = 40
RECOVERY_MAX_BATCHES = 24
RECOVERY_SECONDS = 150
# PublicHttp's two 8-second attempts and its one-second pause on these feeds.
QUOTE_REQUEST_RESERVE = 17
SINA_MARKET = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.'
SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn/'}
SW_API = 'https://www.swsresearch.com/institute-sw/api/'
# Shenwan 2021 level-one identifiers. Keep anchors stable across the direct
# publisher and the independent closing directory, which uses different IDs.
SW_LEVEL_ONE = dict(pair.split('/') for pair in (
    '农林牧渔/801010 基础化工/801030 钢铁/801040 有色金属/801050 电子/801080 家用电器/801110 '
    '食品饮料/801120 纺织服饰/801130 轻工制造/801140 医药生物/801150 公用事业/801160 交通运输/801170 '
    '房地产/801180 商贸零售/801200 社会服务/801210 综合/801230 建筑材料/801710 建筑装饰/801720 '
    '电力设备/801730 国防军工/801740 计算机/801750 传媒/801760 通信/801770 银行/801780 非银金融/801790 '
    '汽车/801880 机械设备/801890 煤炭/801950 石油石化/801960 环保/801970 美容护理/801980'
).split())
EM_WEB_TOKEN = 'bd1d9ddb04089700cf9c27f6f7426281'


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def symbol(code):
    code = str(code).strip().upper()
    prefixed = re.fullmatch(r'(SH|SZ|BJ)(\d{6})', code)
    suffix = prefixed[1] if prefixed else code.partition('.')[2].replace('SS','SH')
    code = prefixed[2] if prefixed else code.split('.')[0]
    if not re.fullmatch(r'\d{6}', code):
        return None
    if code.startswith(('60', '688', '689')):
        return code + '.SH' if suffix in ('', 'SH') else None
    if code.startswith(('000', '001', '002', '003', '300', '301', '302')):
        return code + '.SZ' if suffix in ('', 'SZ') else None
    if code.startswith(('43', '83', '87', '88', '92')):
        return code + '.BJ' if suffix in ('', 'BJ') else None
    return None


def tencent_id(sym):
    bare, exchange = sym.split('.')
    return exchange.lower() + bare


def prior_session(day):
    spec = calendar_data()['exchanges']['XSHG']
    prior = day - timedelta(days=1)
    while not is_session(spec, prior):
        prior -= timedelta(days=1)
    return prior


def quote_rows(text, requested, day):
    """A dated close must agree with its security and include a turnover in 万元."""
    rows = {}
    for market, code, value in re.findall(r'v_(sh|sz|bj)(\d{6})="([^"]*)"', text):
        key = f'{code}.{market.upper()}'
        cells = value.split('~')
        if key not in requested or len(cells) <= 38 or cells[2] != code:
            continue
        try:
            stamp = datetime.strptime(cells[30], '%Y%m%d%H%M%S')
        except ValueError:
            continue
        if stamp.date() != day or stamp.hour < 15:
            continue
        price, prev, amt, pct, turnover = map(number, (cells[i] for i in (3, 4, 37, 32, 38)))
        if price is None or price <= 0 or prev is None or prev <= 0 or amt is None or amt < 0 or pct is None:
            continue
        rows[key] = dict(code=key, name=cells[1], date=day.isoformat(), price=price,
                         amount=amt * 10000, pct=pct / 100,
                         turnoverRate=turnover / 100 if turnover is not None else None)
    return rows


def sina_inventory(http, beijing_only=False, cached_pages=None):
    """The hs_a list contains BJ, SH and SZ. Take no names from an unfinished directory."""
    params = dict(node='hs_a')
    total = int(http.get_json(SINA_MARKET + 'getHQNodeStockCount', params=params, headers=SINA_HEADERS))
    if not 0 < total <= 15000:
        raise ValueError('sina_inventory_count')
    universe = {}
    cache = {} if cached_pages is None else cached_pages
    last = ''
    for page in range(1, (total + 99) // 100 + 1):
        if (total, page) not in cache:
            cache[total, page] = http.get_json(SINA_MARKET + 'getHQNodeData',
                                 params=dict(**params, page=page, num=100, sort='symbol', asc=1), headers=SINA_HEADERS)
        data = cache[total, page]
        if not isinstance(data, list) or len(data) != min(100, total - len(universe)):
            raise ValueError('sina_inventory_page')
        for item in data:
            sym = symbol(item['code'])
            if not sym or tencent_id(sym) != item.get('symbol') or item['symbol'] <= last:
                raise ValueError('sina_inventory_identity')
            last = item['symbol']
            universe[sym] = {}
        if beijing_only and not last.startswith('bj'):
            beijing = {s:{} for s in universe if s.endswith('.BJ')}
            if not beijing:
                raise ValueError('sina_beijing_missing')
            return beijing
    if len(universe) != total or {s[-2:] for s in universe} != {'SH', 'SZ', 'BJ'}:
        raise ValueError('sina_inventory_incomplete')
    return universe


def sina_quotes(http, ids, day):
    url = 'https://hq.sinajs.cn/list=' + ','.join(tencent_id(s) for s in ids)
    text = http.get_text(url, encoding='gb18030', headers=SINA_HEADERS)
    rows = {}
    for exchange, code, record in re.findall(r'hq_str_(sh|sz|bj)(\d{6})="([^"]*)"', text):
        cells = record.split(',')
        sym = code + '.' + exchange.upper()
        if sym not in ids or len(cells) < 32 or not cells[0] or cells[30] != day.isoformat():
            continue
        try:
            observed = datetime.strptime(cells[31], '%H:%M:%S')
        except ValueError:
            continue
        prev, close, amount = (number(cells[i]) for i in (2, 3, 9))
        if observed.hour < 15 or not prev or prev <= 0 or not close or close <= 0 or amount is None or amount < 0:
            continue
        rows[sym] = dict(code=sym, name=cells[0], date=day.isoformat(), price=close, amount=amount,
                         pct=round((close / prev - 1) * 100, 2) / 100, turnoverRate=None)
    return rows


def clist(http, scope, fields, url=CLIST):
    """Stable security-code order; truncated, duplicate or changing pages invalidate the list."""
    rows, expected = {}, None
    for page in range(1, 151):
        obj = http.get_json(url, params=dict(fs=scope, pn=page, pz=100, po=0, np=1,
                            fid='f12', fltt=2, invt=2, fields=fields, ut=EM_WEB_TOKEN))
        data = obj['data']
        count = int(data['total'])
        if count <= 0 or (expected is not None and count != expected):
            raise ValueError('inventory_total')
        expected = count
        items = data['diff']
        if not isinstance(items, list) or not items:
            raise ValueError('inventory_page')
        for row in items:
            key = row['f12']
            if not isinstance(key, str) or not key or key in rows:
                raise ValueError('inventory_overlap')
            rows[key] = row
        if len(rows) == expected:
            return list(rows.values())
        if len(rows) > expected:
            break
    raise ValueError('inventory_incomplete')


def tdx_inventory(tdx, market):
    # The security-list wire protocol may return fewer rows than the requested
    # page size. Advance by actual records and bind coverage to its reported total.
    api = tdx.client
    total = api.get_security_count(market)
    if not isinstance(total, int) or not 0 < total <= 100000:
        raise ValueError('tdx_inventory_count')
    listed, keys = {}, set()
    while len(keys) < total:
        page = api.get_security_list(market, len(keys))
        if not page:
            raise ValueError('tdx_inventory_page')
        for item in page:
            code = item['code']
            if code in keys:
                raise ValueError('tdx_inventory_overlap')
            keys.add(code)
            sym = symbol(code)
            if sym and sym.endswith(('.SZ', '.SH')[market]):
                listed[sym] = {}
    if len(keys) != total or not listed:
        raise ValueError('tdx_inventory_incomplete')
    return listed


def _inventory_records(records):
    found = {}
    for item in records:
        sym = symbol(item['f12'])
        if not sym:
            raise ValueError('unknown_mainland_code')
        metadata = {}
        try:
            listed = datetime.strptime(str(item.get('f26')), '%Y%m%d').date()
            metadata['listed'] = listed.isoformat()
        except ValueError:
            pass
        found[sym] = metadata
    return found


def suspension_list(http, day):
    """Accept full-session suspension windows, never resumed/intraday halts."""
    opening = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=30)
    closing = opening.replace(hour=15, minute=0)
    paused = set()
    for page in range(1, 21):
        result = http.get_json('https://datacenter-web.eastmoney.com/api/data/v1/get', params=dict(
            reportName='RPT_CUSTOM_SUSPEND_DATA_INTERFACE', source='WEB', client='WEB', columns='ALL',
            filter=f'(MARKET="全部")(DATETIME=\'{day.isoformat()}\')', sortColumns='SECURITY_CODE',
            sortTypes=1, pageSize=500, pageNumber=page))['result']
        for row in result['data']:
            try:
                start = datetime.fromisoformat(row['SUSPEND_START_TIME'])
                end = row.get('SUSPEND_END_TIME')
                resume = row.get('PREDICT_RESUME_DATE')
                if start > opening or (end and datetime.fromisoformat(end) < closing):
                    continue
                if not end and (row['SUSPEND_EXPIRE'] not in ('全天停牌','连续停牌','停牌1天','停牌一天')
                                or (resume and date.fromisoformat(resume[:10]) <= day)):
                    continue
                sym = symbol(row['SECURITY_CODE'])
                if sym and row.get('SECUCODE', sym) == sym:
                    paused.add(sym)
            except (KeyError, TypeError, ValueError):
                continue
        if page >= int(result['pages']):
            return paused
    raise ValueError('suspension_page_limit')


def em_closed_stock(row, day):
    """Fallback quotes require the same per-security evening date proof."""
    epoch = number(row.get('f124'))
    stamp = datetime.fromtimestamp(epoch, BJ) if epoch else None
    price, pct, amount, rate = (number(row.get(f)) for f in ('f2','f3','f6','f8'))
    if (not stamp or stamp.date() != day or stamp.hour < 15 or price is None or price <= 0 or
            amount is None or amount < 0 or pct is None or not isinstance(row.get('f14'),str)):
        return None
    return dict(code=symbol(row['f12']), date=day.isoformat(), name=row['f14'], price=price,
                pct=pct/100, amount=amount, turnoverRate=None if rate is None else rate/100)


def dataframe_rows(frame):
    return [] if frame is None else frame.to_dict('records')


def tencent_days(http, sym, day):
    slug = tencent_id(sym)
    data = http.get_json('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                         params={'param': f'{slug},day,,{day.isoformat()},45,'})
    klines = data['data'][slug]['day']
    return [(str(k[0]), number(k[2])) for k in klines]


def daily_series(tdx, http, sym, day):
    dates = []
    if tdx is not None and not sym.endswith('.BJ'):
        try:
            rows = dataframe_rows(tdx.bars(symbol=sym[:6], frequency=9, offset=45))
            dates = [(str(r['datetime'])[:10], number(r['close'])) for r in rows]
        except Exception:
            pass
    if not any(key == day.isoformat() and close for key, close in dates):
        dates = tencent_days(http, sym, day)
    prices = {key:close for key, close in dates if key <= day.isoformat() and close is not None and close > 0}
    if day.isoformat() not in prices:
        raise ValueError('missing_same_session_bar')
    return sorted(prices.items())


def core_symbols(radar):
    ids = set()
    for node in radar.get('companies', []):
        if (node.get('mkt') or node.get('market')) == 'A股':
            sym = symbol(node.get('sym')) or symbol(node.get('code'))
            if sym:
                ids.add(sym)
    return ids


def tradable_name(name):
    name = name.strip().upper()
    return not (re.match(r'^(?:S?\*?ST|N|C)', name) or '退市' in name or name.endswith('退'))


def enrich_candidates(rows, core, day, series):
    """Query age and prices only for the two ranking frontiers and radar names."""
    checked = set()

    def enrich(row):
        sym = row['code']
        if sym not in checked:
            checked.add(sym)
            values = series(sym)
            if values:
                row['listedBefore'] = values[0][0]
                row['spark'] = [v for _, v in values[-5:]]
        return row

    active = [r for r in rows if r['amount'] >= 1e9 and tradable_name(r['name'])]
    for direction in (1, -1):
        order = sorted((r for r in active if direction * r['pct'] > 0),
                       key=lambda r: (-direction * r['pct'], r['code']))
        found = 0
        for row in order:
            if not row.get('listed') and len(checked) >= 80 and row['code'] not in checked:
                continue
            listed = row.get('listed') or enrich(row).get('listedBefore')
            if listed and (day - date.fromisoformat(listed)).days >= 30:
                enrich(row)
                found += 1
                if found == 5:
                    break
    for row in rows:
        if row['code'] in core:
            enrich(row)


def board_candles(http, code, day, frequency):
    obj = http.get_json(KLINE, params=dict(secid='90.' + code, klt=frequency, fqt=0,
                        end=day.strftime('%Y%m%d'), lmt=100 if frequency != 101 else 6,
                        fields1='f1,f2,f3,f4,f5,f6', fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59'))
    data = obj['data']
    if data.get('code') != code:
        raise ValueError('board_identity')
    bars = {}
    for line in data['klines']:
        cells = line.split(',')
        close = number(cells[2])
        if cells[0] in bars:
            raise ValueError('board_duplicate_bar')
        if close and close > 0:
            bars[cells[0]] = (close, number(cells[6]) if len(cells)>6 else None,
                              number(cells[8]) if len(cells)>8 else None)
    return bars


def board_history(http, code, day, frequency):
    return sorted((stamp, bar[0]) for stamp,bar in board_candles(http,code,day,frequency).items())


def board_net_flow(http, code, day):
    data = http.get_json('https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get',
        params=dict(secid='90.'+code, klt=101, lmt=10, fields1='f1,f2,f3,f7',
                    fields2='f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65'))['data']
    if data.get('code') != code:
        raise ValueError('board_flow_identity')
    observed = [line.split(',') for line in data['klines'] if line.split(',',1)[0] == day.isoformat()]
    if len(observed) != 1 or len(observed[0]) < 6:
        raise ValueError('board_flow_day')
    net, large, super_large = (number(observed[0][i]) for i in (1,4,5))
    # Main orders are the large and super-large series, all three in CNY.
    if None in (net,large,super_large) or abs(net-large-super_large) > max(2,abs(net)*1e-6):
        raise ValueError('board_flow_components')
    return net


def timed_points(pairs, name, day, prev, code=None):
    if prev is None or prev <= 0:
        return []
    points = []
    for stamp, price in pairs:
        if stamp[:10] == day.isoformat() and stamp[11:16] in TARGET_TIMES - {'09:25'} and price and price > 0:
            point = dict(date=day.isoformat(), time=stamp[11:16], name=name, pct=price / prev - 1)
            if code:
                point['code'] = code
            points.append(point)
    return points


def em_session_points(http, secid, name, day, *, board=False):
    """iscr/iscca request auction bars; a priced indication with no execution is insufficient."""
    data = http.get_json('https://push2his.eastmoney.com/api/qt/stock/trends2/get', params=dict(
        secid=secid, fields1='f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13',
        fields2='f51,f52,f53,f54,f55,f56,f57,f58',ndays=1,iscr=1,iscca=1))['data']
    exch, code = secid.split('.')
    prev = number(data.get('preClose'))
    if (data.get('code') != code or str(data.get('market')) != exch or
            not prev or prev <= 0 or (not board and data.get('name')!=name)):
        raise ValueError('trends_identity')
    bars = {}
    for line in data['trends']:
        cells = line.split(',')
        if len(cells)<7 or not re.fullmatch(re.escape(day.isoformat()) + r' \d{2}:\d{2}', cells[0]):
            continue
        clock = cells[0][11:]
        if clock not in TARGET_TIMES:
            continue
        if clock in bars:
            raise ValueError('trends_duplicate')
        bars[clock] = (number(cells[2]), number(cells[5]), number(cells[6]))
    closing = bars.get('15:00',(None,))[0]
    if closing is None or closing <= 0:
        raise ValueError('trends_unclosed')
    pairs = [(f'{day} {clock}',values[0]) for clock,values in bars.items()]
    points = timed_points(pairs,name,day,prev,code if board else None)
    price, volume, amount = bars.get('09:25', (None,None,None))
    if all(v is not None and v > 0 for v in (price,volume,amount)):
        auction = dict(date=day.isoformat(), time='09:25', name=name, pct=price/prev-1,
                       auctionConfirmed=True)
        if board:
            auction['code'] = code
        points.insert(0,auction)
    return points


class _BoardPage(HTMLParser):
    """Read the public board table cells, excluding links to individual stocks."""
    def __init__(self, html):
        super().__init__()
        self.chunks, self.rows, self.row = [], [], {}
        self.column, self.sector = '', None
        self.members, self.stock = [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'tr':
            self.row, self.sector, self.stock = {}, None, None
        elif tag == 'td':
            self.column = attrs.get('data-label', '')
        elif tag == 'a' and self.column == '概念':
            match = re.fullmatch(r'/bk/(\d{1,5})\.html', attrs.get('href', ''))
            if match:
                self.sector = int(match[1])
        elif tag == 'a' and self.column == '股票名称 / 代码':
            match = re.fullmatch(r'/stock/(\d{6})/', attrs.get('href', ''))
            if match:
                self.stock = match[1]

    def handle_data(self, value):
        if text := value.strip():
            self.chunks.append(text)
            if self.column:
                self.row[self.column] = self.row.get(self.column, '') + text

    def handle_endtag(self, tag):
        if tag == 'td':
            self.column = ''
        elif tag == 'tr' and self.sector is not None:
            self.rows.append((self.sector, self.row))
        elif tag == 'tr' and self.stock is not None:
            match = re.search(r'(\d{6}\.(?:SH|SZ|BJ))$', self.row.get('股票名称 / 代码',''))
            if match and match[1][:6] == self.stock and symbol(match[1]) == match[1]:
                self.members.append(match[1])


def published_concepts(http, day):
    """The public closing directory identifies its boards as BK….DC on their detail pages."""
    url = 'https://www.zhunshangshi.com/bk/'
    rows, expected = {}, None
    for page_num in range(1, 61):
        page = _BoardPage(http.get_text(url, params={'type':'concept','page':page_num}))
        header = re.search(r'概念板块行情一览\s*当前数据日期更新于\s*(\d{4}-\d{2}-\d{2})\s*·\s*共\s*(\d+)\s*个板块',
                           ' '.join(page.chunks))
        if not header or header[1] != day.isoformat() or not page.rows:
            raise ValueError('published_concept_date')
        count = int(header[2])
        if expected is not None and count != expected:
            raise ValueError('published_concept_total')
        expected = count
        for board_id, cells in page.rows:
            raw_pct = re.fullmatch(r'([+−\-]?\d+(?:\.\d+)?)%', cells['涨跌幅'])
            if not raw_pct or board_id in rows or not cells['概念']:
                raise ValueError('published_concept_identity')
            pct = float(raw_pct[1].replace('−','-')) / 100
            rows[board_id] = dict(code=f'BK{board_id:04d}', name=cells['概念'], date=day.isoformat(),
                pct=pct, amount=None, netFlow=None, source='准上市东财代码概念榜', reason='准上市收盘汇总，板块驱动待核')
        if len(rows) >= expected:
            break
    if not rows or len(rows) != expected:
        raise ValueError('published_concept_incomplete')
    ordered = sorted(rows.items(), key=lambda pair:(pair[1]['pct'],pair[0]))
    for board_id, row in dict(ordered[:5] + ordered[-5:]).items():
        detail_page = _BoardPage(http.get_text(f'{url}{board_id}.html'))
        detail = ' '.join(detail_page.chunks)
        proof = re.search(r'板块代码\s+(BK\d+)\.DC\s+最新交易日\s+(\d{4}-\d{2}-\d{2})\s+当日涨跌幅\s+([+−\-]?[\d.]+)%', detail)
        if (not proof or proof[1] != row['code'] or proof[2] != day.isoformat()
                or float(proof[3].replace('−','-')) / 100 != row['pct']):
            raise ValueError('published_concept_crosscheck')
        header = re.search(re.escape(row['name']) + r'板块股票\s+行情日期\s+(\d{4}-\d{2}-\d{2})\s*·\s*按当日涨跌幅排序\s*·\s*共\s*(\d+)\s*只',detail)
        unique = set(detail_page.members)
        if (header and header[1] == day.isoformat() and unique and
                len(unique) == len(detail_page.members) <= int(header[2])):
            row['constituents'] = sorted(unique)
            row['constituentsComplete'] = len(unique) == int(header[2])
    return list(rows.values()), []


def boards(http, scope, day, attempt, url=CLIST):
    fields = 'f12,f14,f3,f6,f62,f124'
    raw = clist(http, scope, fields, url)
    rows = []
    for item in raw:
        epoch = number(item.get('f124'))
        observed = datetime.fromtimestamp(epoch, BJ) if epoch else None
        pct = number(item['f3'])
        if (not observed or observed.date() != day or observed.hour < 15 or pct is None or
                not re.fullmatch(r'BK\d+', item['f12'])):
            raise ValueError('board_date_or_value')
        rows.append(dict(code=item['f12'], name=item['f14'], date=day.isoformat(),
                         pct=pct/100, amount=number(item.get('f6')), netFlow=number(item.get('f62'))))
    return em_board_details(http, rows, day, attempt)


def em_board_details(http, rows, day, attempt):
    """Enrich only the ranking frontiers, using exactly the same Eastmoney BK identity."""
    rows.sort(key=lambda r:(r['pct'], r['code']))
    if not rows:
        return rows, []
    extremes = {rows[-1]['code'], rows[0]['code']}
    # Visit the two extremes first. Stop polling a broken feed after two
    # consecutive failures, independently for price and flow.
    selected = {r['code']:r for r in [rows[-1], rows[0], *rows[-5:], *rows[:5]]}
    date_keys = [day]
    for _ in range(5):
        date_keys.insert(0,prior_session(date_keys[0]))
    keys = [d.isoformat() for d in date_keys]
    segments = []
    date_errors = flow_errors = 0
    for code,row in selected.items():
        if date_errors < 2:
            def daily():
                bars = board_candles(http, code, day, 101)
                close, amount, reported_pct = bars[keys[-1]]
                prior = bars[keys[-2]][0]
                pct = reported_pct if reported_pct is not None else 100*(close/prior-1)
                if abs(pct-100*row['pct']) > 0.02:
                    raise ValueError('board_daily_return_mismatch')
                if amount is not None and amount >= 0 and row.get('amount') is None:
                    row['amount'] = amount
                if all(k in bars for k in keys[-5:]):
                    row['spark'] = [bars[k][0] for k in keys[-5:]]
                    if keys[0] in bars:
                        row['fiveDayReturn'] = close/bars[keys[0]][0]-1
                return prior
            prior = attempt('board_daily_missing', daily)
            date_errors = 0 if prior is not None else date_errors+1
        else:
            prior = None
        if code in extremes:
            def checked_minutes(pts):
                closing = next((p['pct'] for p in pts if p['time']=='15:00'),None)
                if closing is None or abs(closing-row['pct']) > .0003:
                    raise ValueError('board_minute_return_mismatch')
                return pts
            pts = attempt('board_auction_or_minutes_missing', lambda:checked_minutes(
                em_session_points(http, '90.'+code, row['name'], day, board=True)), [])
            if prior and not {'10:30','13:30','15:00'} <= {p['time'] for p in pts}:
                def five_minute_bars():
                    bars = board_history(http, code, day, 5)
                    return checked_minutes(timed_points(bars,row['name'],day,prior,code))
                seen = {p['time'] for p in pts}
                pts.extend(p for p in attempt('board_intraday_missing',five_minute_bars,[]) if p['time'] not in seen)
            segments.extend(pts)
        if row.get('netFlow') is None and flow_errors < 2:
            flow = attempt('board_flow_missing', lambda:board_net_flow(http,code,day))
            if flow is not None:
                row['netFlow'] = flow
                flow_errors = 0
            else:
                flow_errors += 1
    return rows, segments


def index_points(tdx, day, name, code):
    daily = dataframe_rows(tdx.index_bars(symbol=code, frequency=9, offset=45))
    prices = {str(r['datetime'])[:10]:number(r['close']) for r in daily}
    prev = prices.get(prior_session(day).isoformat())
    intraday = dataframe_rows(tdx.index_bars(symbol=code, frequency=0, offset=240))
    pairs = [(str(r['datetime']), number(r['close'])) for r in intraday]
    return timed_points(pairs, name, day, prev)


def tencent_index_points(http, day, name, slug):
    data = http.get_json('https://web.ifzq.gtimg.cn/appstock/app/minute/query',
                         params={'code': slug})['data'][slug]
    lines = data['data']
    quote = data['qt'][slug]
    stamp = datetime.strptime(quote[30], '%Y%m%d%H%M%S')
    if (lines['date'] != day.strftime('%Y%m%d') or quote[2] != slug[2:]
            or stamp.date() != day or stamp.hour < 15):
        raise ValueError('minute_date')
    pairs = []
    for row in lines['data']:
        parts = row.split()
        if len(parts) >= 2 and re.fullmatch(r'\d{4}', parts[0]):
            clock = parts[0]
            pairs.append((f'{day} {clock[:2]}:{clock[2:]}', number(parts[1])))
    return timed_points(pairs, name, day, number(quote[4]))


def sw_industries(http, day, attempt):
    """First-party Shenwan level-one daily report. Volume is not cash turnover."""
    def report(start, end):
        records = {}
        expected = None
        for page in range(1, 11):
            result = http.get_json(SW_API + 'index_analysis/index_analysis_report/', params=dict(
                page=page, page_size=100, index_type='一级行业', type='DAY', swindexcode='all',
                start_date=start.isoformat(), end_date=end.isoformat()))['data']
            count = int(result['count'])
            if count <= 0 or (expected is not None and count != expected) or not result['results']:
                raise ValueError('sw_page')
            expected = count
            for r in result['results']:
                date_key = date.fromisoformat(str(r['bargaindate'])[:10])
                code = str(r['swindexcode'])
                key = (code, date_key)
                if not start <= date_key <= end or not re.fullmatch(r'\d{6}', code) or key in records:
                    raise ValueError('sw_identity')
                records[key] = r
            if len(records) == expected:
                return records
        raise ValueError('sw_incomplete')

    current = report(day, day)
    rows = []
    for (code, _), item in current.items():
        pct, close = number(item['markup']), number(item['closeindex'])
        if pct is None or close is None or close <= 0 or not item['swindexname']:
            raise ValueError('sw_close')
        rows.append(dict(code='SW'+code, name=item['swindexname'], date=day.isoformat(),
                         pct=pct/100, price=close, amount=None, netFlow=None))
    days = [day]
    for _ in range(5):
        days.insert(0, prior_session(days[0]))
    history = attempt('board_daily_missing', lambda:report(days[0], days[-2]), {})
    for row in rows:
        code = row['code'][2:]
        values = [number(history.get((code, d), {}).get('closeindex')) for d in days[:-1]] + [row['price']]
        if all(v is not None and v > 0 for v in values[1:]):
            row['spark'] = values[1:]
            if values[0] and values[0] > 0:
                row['fiveDayReturn'] = values[-1] / values[0] - 1
    return rows, sw_extreme_points(http,rows,day,attempt)


def sw_extreme_points(http, rows, day, attempt):
    ordered = sorted(rows, key=lambda r:(r['pct'],r['code']))
    points = []
    for row in {r['code']:r for r in (ordered[0],ordered[-1])}.values():
        def minutes():
            if len(row.get('spark',[])) < 2:
                raise ValueError('sw_previous_close')
            code = row['code'][2:]
            data = http.get_json(SW_API+'index_publish/details/timelines/', params={'swindexcode':code})['data']
            pairs = [(str(r['trading_date'])[:10]+' '+str(r['trading_time']),number(r['l8']))
                     for r in data if str(r['l1'])==code]
            seen = timed_points(pairs,row['name'],day,row['spark'][-2],row['code'])
            if not seen:
                raise ValueError('sw_minutes_missing')
            return seen
        points.extend(attempt('board_intraday_missing',minutes,[]))
    return points


def sw_members(http, row, day):
    """The public Shenwan directory labels its date and full or truncated constituent list."""
    code = SW_LEVEL_ONE[row['name']]
    if row['code'] != 'SW' + code:
        raise ValueError('sw_members_identity')
    url = 'https://www.yyqyx.com/b/' + code + '.SI'
    page = http.get_text(url)
    if f'<link rel="canonical" href="{url}">' not in page:
        raise ValueError('sw_members_identity')
    text = ' '.join(_BoardPage(page).chunks)
    proof = re.search(re.escape(row['name']) + r' 申万一级行业 ([+−\-]?[\d.]+)% 主力净额 .{1,40}? 成分股 (\d+) 只 数据日 (\d{4}-\d{2}-\d{2})', text)
    if (not proof or proof[3] != day.isoformat() or
            abs(float(proof[1].replace('−','-')) - 100*row['pct']) > .02):
        raise ValueError('sw_members_date_or_return')
    section = re.search(r'<h2 id="sec5">全部成分股（按代码）</h2>\s*<p[^>]*>共\s*(\d+)\s*只成分股[^<]*</p>\s*<div class="tags">(.*?)</div>',page,re.S)
    if not section or section[1] != proof[2]:
        raise ValueError('sw_members_table')
    links = re.findall(r'<a\b[^>]*\bhref="([^"]+)"',section[2])
    members = []
    for link in links:
        match = re.fullmatch(r'(?:https://www\.yyqyx\.com)?/s/(\d{6}\.(?:SZ|SH|BJ))',link)
        if not match or symbol(match[1]) != match[1]:
            raise ValueError('sw_members_symbol')
        members.append(match[1])
    total = int(proof[2])
    if not members or len(set(members)) != len(members) or len(members) > total:
        raise ValueError('sw_members_count')
    return dict(constituents=sorted(members),constituentsComplete=len(members)==total)


def constituent_turnover(boards, quotes, halted, day):
    """Fill turnover only from complete dated membership and every member's terminal status."""
    for row in boards:
        if (row.get('amount') is not None or row.get('constituentsComplete') is not True
                or row.get('date') != day.isoformat()):
            continue
        members = set(row.get('constituents', []))
        if not members or not members <= quotes.keys() | halted:
            continue
        traded = [quotes[s] for s in members - halted]
        if all(r.get('date') == day.isoformat() and number(r.get('amount')) is not None
               and r['amount'] >= 0 for r in traded):
            row['amount'] = sum(r['amount'] for r in traded)
            row['amountSource'] = '同日已核完整成分成交额合计'


def published_sw_industries(http, day):
    """Reconcile the public Shenwan 2021 daily directory to six dated index closes."""
    def public_table(filename, assignment):
        text = http.get_text('https://alphaonly.com.cn/data/' + filename)
        # The files contain a JSON literal, sometimes preceded by an attribution
        # comment. Never execute publisher JavaScript.
        pattern = r'(?:\s*//[^\n]*\n)*\s*window\.' + assignment + r'\s*=\s*(\{.*\})\s*;?\s*'
        match = re.fullmatch(pattern, text, flags=re.S)
        if not match:
            raise ValueError('sw_public_payload')
        data = json.loads(match[1])
        if data['as_of'] != day.isoformat():
            raise ValueError('sw_public_day')
        return data

    table = public_table('industry-data.js', 'INDUSTRY_DATABASE')
    series = public_table('industry-gldi-summary.js', 'INDUSTRY_GLDI_HISTORY')
    history = series['industries']
    if (table.get('source') != 'AlphaOnly申万一级行业日度数据' or set(history) != SW_LEVEL_ONE.keys()
            or len(table['rows']) != len(SW_LEVEL_ONE)):
        raise ValueError('sw_public_coverage')
    dates = [day]
    for _ in range(5):
        dates.insert(0, prior_session(dates[0]))
    if series['dates'][-6:] != [d.isoformat() for d in dates]:
        raise ValueError('sw_public_sessions')

    result = {}
    for record in table['rows']:
        name = record['industry_name']
        if name not in SW_LEVEL_ONE or name in result:
            raise ValueError('sw_public_identity')
        values = history[name]['close']
        if len(values) != len(series['dates']):
            raise ValueError('sw_public_series')
        closes = [number(x) for x in values[-6:]]
        if any(x is None or x <= 0 for x in closes):
            raise ValueError('sw_public_close')
        daily, weekly = (closes[-1]/closes[i] - 1 for i in (-2,-6))
        for observed, column in ((daily, 'ret_1d'), (weekly, 'ret_5d')):
            reported = number(record[column])
            if reported is None or abs(100*observed - reported) > 0.01:
                raise ValueError('sw_public_return')
        # The public index series has no intraday observations or net flow.
        # The cash amount in the companion directory does not declare its unit.
        result[name] = dict(code='SW'+SW_LEVEL_ONE[name], name=name, date=day.isoformat(),
                            pct=daily, price=closes[-1], spark=closes[-5:], fiveDayReturn=weekly,
                            amount=None, netFlow=None, source='AlphaOnly申万一级行业日度数据',
                            reason='AlphaOnly申万一级行业收盘汇总，板块驱动待核')
    return list(result.values()), []


def limit_pool(http, endpoint, day):
    ordering = {'getTopicZTPool':'fbt:asc', 'getTopicDTPool':'fund:asc',
                'getTopicZBPool':'fbt:asc', 'getYesterdayZTPool':'zs:desc'}
    data = http.get_json('https://push2ex.eastmoney.com/' + endpoint, params=dict(
        ut='7eea3edcaed734bea9cbfc24409ed989', dpt='wz.ztzt', Pageindex=0, pagesize=10000,
        sort=ordering[endpoint], date=day.strftime('%Y%m%d')))['data']
    # The endpoint can return the latest session despite an explicit date parameter.
    if str(data['qdate']) != day.strftime('%Y%m%d') or int(data['tc']) != len(data['pool']):
        raise ValueError('pool_date_or_page')
    rows = []
    for r in data['pool']:
        pct = number(r['zdp'])
        sym = symbol(r['c'])
        if pct is None or not sym:
            raise ValueError('pool_value')
        item = dict(code=sym, name=r['n'], pct=pct / 100)
        if endpoint in ('getTopicZTPool','getYesterdayZTPool'):
            height = int(r['lbc'] if endpoint == 'getTopicZTPool' else r['ylbc'])
            if height < 1:
                raise ValueError('pool_height')
            item['height'] = height
        rows.append(item)
    if len({r['code'] for r in rows}) != len(rows):
        raise ValueError('pool_duplicates')
    return rows


def hot_reasons(http, day):
    # This THS endpoint serves a GBK body even when its MIME type says JSON.
    import json
    url = f'https://zx.10jqka.com.cn/event/api/getharden/date/{day}/orderby/date/orderway/desc/charset/GBK/'
    obj = json.loads(http.get_text(url, encoding='gb18030'))
    if obj.get('errocode', 0) not in (0, '0') or not isinstance(obj['data'], list):
        raise ValueError('ths_hot_unavailable')
    return {symbol(r.get('code')):r['reason'] for r in obj['data']
            if str(r.get('date', ''))[:10] == day.isoformat() and isinstance(r.get('reason'), str)}


def open_tdx():
    from mootdx.quotes import Quotes
    return Quotes.factory(market='std', timeout=4, heartbeat=False, auto_retry=False)


def _record_failures(warnings):
    def attempt(code, work, fallback=None):
        try:
            return work()
        except Exception:
            # Library exceptions can include gateway details. Emit only fixed codes.
            warnings.add(code)
            return fallback
    return attempt


BOARD_FEEDS = {'industries':('industry_boards_missing',2,'17'),
               'concepts':('concept_boards_missing',3,'79')}


def _load_board(day, panel, http, warnings):
    attempt = _record_failures(warnings)
    err, kind, host = BOARD_FEEDS[panel]
    scope = f'm:90 t:{kind} f:!50'
    result = attempt(err, lambda:boards(http, scope, day, attempt))
    if result is None:
        result = attempt(err, lambda:boards(http, scope, day, attempt, CLIST.replace('push2.',host+'.push2.')))
    if result is None and panel == 'industries':
        result = attempt(err, lambda:sw_industries(http, day, attempt))
        if result is None:
            result = attempt(err, lambda:published_sw_industries(http, day))
            if result:
                result = (result[0],sw_extreme_points(http,result[0],day,attempt))
    if result is None and panel == 'concepts':
        result = attempt(err, lambda:published_concepts(http, day))
        if result:
            result = em_board_details(http,result[0],day,attempt)
    if not result or not result[0]:
        warnings.add(err)
        return [], []
    warnings.discard(err)
    sw = sorted((r for r in result[0] if r['code'].startswith('SW')),key=lambda r:(r['pct'],r['code']))
    if sw:
        failures = 0
        for row in {r['code']:r for r in [sw[-1],sw[0],*sw[-5:],*sw[:5]]}.values():
            members = attempt('sw_members_missing',lambda:sw_members(http,row,day))
            if members is None:
                failures += 1
                if failures >= 2:
                    break
            else:
                row.update(members)
                failures = 0
    return result


def retry_missing_boards(day, raw, http):
    """Recover missing complete dated board lists without refreshing accepted observations."""
    revised = dict(raw)
    if raw.get('date') != day.isoformat():
        return revised
    quotes = {r['code']:r for r in raw.get('stocks') or [] if r.get('date') == day.isoformat() and r.get('code')}
    for panel in BOARD_FEEDS:
        if raw.get(panel):
            continue
        err = BOARD_FEEDS[panel][0]
        errors = set()
        try:
            rows, points = _load_board(day,panel,http,errors)
        except Exception:
            continue
        if not rows or any(row.get('date') != day.isoformat() for row in rows):
            continue
        # Raw snapshots omit proven halts. Only sum a board when every member
        # has a retained dated stock quote; otherwise keep its turnover absent.
        constituent_turnover(rows,quotes,set(),day)
        revised[panel] = rows
        existing = revised.get('intraday') or []
        merged = list(existing)
        seen = {(p.get('date'),p.get('time'),p.get('code') or p.get('name')) for p in existing}
        board_ids = {row['code'] for row in rows}
        for p in points:
            if p.get('date') != day.isoformat() or p.get('code') not in board_ids:
                continue
            key = (p['date'],p['time'],p['code'])
            if key not in seen:
                merged.append(p)
                seen.add(key)
        revised['intraday'] = merged
        warnings = [w for w in revised.get('warnings',[]) if w != err]
        revised['warnings'] = warnings + sorted(errors.difference(warnings))
    return revised


def collect_market(day, radar, http):
    warnings = set()
    started = datetime.now(BJ)
    sentiment_at = started.replace(hour=20, minute=15, second=0, microsecond=0)
    staged = started.date() == day and started < sentiment_at
    attempt = _record_failures(warnings)

    core = core_symbols(radar)
    tdx = attempt('tdx_unavailable', open_tdx)
    try:
        universe = {}
        if tdx is not None:
            for market in (0, 1):
                universe.update(attempt('tdx_inventory_incomplete', lambda:tdx_inventory(tdx, market), {}))
        cache = {}
        bse = attempt('beijing_inventory_missing', lambda:_inventory_records(clist(http, BEIJING, 'f12,f26')), {})
        if not bse:
            bse = attempt('beijing_inventory_missing', lambda:sina_inventory(http, True, cache), {})
            if bse:
                warnings.discard('beijing_inventory_missing')
        universe.update(bse)
        covered = bool({s[-2:] for s in universe} == {'SH','SZ','BJ'} and bse)
        em_rows = []
        em_fields = 'f12,f26,f14,f2,f3,f6,f8,f124'
        quotes = {}
        def reconcile_inventory():
            nonlocal em_rows, covered, universe
            em_rows = attempt('mainland_inventory_incomplete', lambda:clist(http, ALL_A, em_fields), [])
            directory = attempt('unknown_mainland_code', lambda:_inventory_records(em_rows), {})
            if {s[-2:] for s in directory} != {'SH','SZ','BJ'}:
                directory = attempt('sina_inventory_missing', lambda:sina_inventory(http, cached_pages=cache), {})
            if directory:
                universe = {s:{**universe.get(s, {}), **meta} for s,meta in directory.items()}
                covered = True
                warnings.difference_update({'beijing_inventory_missing','mainland_inventory_incomplete'})

        def read_batch(ids, deadline=None):
            url = 'https://qt.gtimg.cn/q=' + ','.join(tencent_id(s) for s in ids)
            text = attempt('tencent_batch_missing', lambda:http.get_text(url, encoding='gb18030'), '')
            quotes.update(quote_rows(text, set(ids), day))
            unresolved = [s for s in ids if s not in quotes]
            if unresolved and (deadline is None or time.monotonic() + QUOTE_REQUEST_RESERVE < deadline):
                quotes.update(attempt('sina_quotes_missing', lambda:sina_quotes(http, unresolved, day), {}))

        queried = set()
        def fill_quotes():
            requested = sorted((universe.keys() | core) - queried - quotes.keys())
            for start in range(0, len(requested), 60):
                read_batch(requested[start:start+60])
            queried.update(requested)
            for item in em_rows:
                row = em_closed_stock(item, day)
                if row:
                    quotes.setdefault(row['code'], row)

        used_directory = not covered
        if used_directory:
            reconcile_inventory()
        fill_quotes()
        missing = universe.keys() - quotes.keys()
        need_halts = missing or core - quotes.keys()
        halted = attempt('suspensions_missing', lambda:suspension_list(http, day), set()) if need_halts else set()
        if missing - halted and not used_directory:
            # Delisted names can remain in the TDX directory. Bind any revision to
            # an independent complete directory; request newly discovered names too.
            reconcile_inventory()
            fill_quotes()
        # Revisit only unresolved members of the final roster (and tracked core),
        # after already dated quotes and proven full-day halts have been removed.
        unresolved = sorted((universe.keys() | core) - quotes.keys() - halted,
                            key=lambda sym:(sym not in core, sym))
        budget = RECOVERY_SECONDS
        if staged:
            budget = min(budget, (sentiment_at - datetime.now(BJ)).total_seconds())
        deadline = time.monotonic() + budget
        limit = min(len(unresolved), RECOVERY_BATCH_SIZE * RECOVERY_MAX_BATCHES)
        for start in range(0, limit, RECOVERY_BATCH_SIZE):
            if time.monotonic() + QUOTE_REQUEST_RESERVE >= deadline:
                break
            read_batch(unresolved[start:start+RECOVERY_BATCH_SIZE], deadline)
        for sym, row in quotes.items():
            row.update(universe.get(sym, {}))
            row['inMarketUniverse'] = sym in universe
        # No previous-date close, including a suspended stock, enters a ranking.
        complete = bool(covered and universe.keys() <= quotes.keys() | halted)
        if not complete:
            warnings.add('market_coverage_partial')
        else:
            warnings.difference_update({'tencent_batch_missing','sina_quotes_missing'})
        if core - quotes.keys() - halted:
            warnings.add('core_quotes_partial')
        rows = [r for sym, r in quotes.items() if sym not in halted and
                r['amount'] > 0 and (sym in universe or not complete or sym in core)]
        # The amount and breadth concern the three-exchange universe only.
        breadth = {}
        if complete:
            traded = [r for r in rows if r['code'] in universe]
            breadth.update(up=sum(r['pct'] > 0 for r in traded), flat=sum(r['pct'] == 0 for r in traded),
                           down=sum(r['pct'] < 0 for r in traded), turnoverCny=sum(r['amount'] for r in traded))
        enrich_candidates(rows if complete else [r for r in rows if r['code'] in core], core, day,
                          lambda sym:attempt('stock_history_missing', lambda:daily_series(tdx, http, sym, day), []))
        intraday = []
        for name, slug in [('上证指数','sh000001'), ('创业板指','sz399006')]:
            pts = attempt('tdx_index_missing', lambda:index_points(tdx, day, name, slug[2:]), []) if tdx else []
            times = {p['time'] for p in pts}
            secid = ('1.' if slug.startswith('sh') else '0.') + slug[2:]
            auction = attempt('auction_0925_missing',lambda:em_session_points(http,secid,name,day),[])
            pts.extend(p for p in auction if p['time'] not in times)
            times.update(p['time'] for p in auction)
            if '09:25' not in times:
                warnings.add('auction_0925_missing')
            if not {'10:30','13:30','15:00'} <= times:
                fallback = attempt('index_intraday_missing', lambda:tencent_index_points(http, day, name, slug), [])
                pts.extend(p for p in fallback if p['time'] not in times)
            if not {'10:30','13:30','15:00'} <= {p['time'] for p in pts}:
                warnings.add('index_intraday_missing')
            intraday.extend(pts)
    finally:
        if tdx is not None:
            attempt('tdx_close_failed', tdx.close)

    industries, pts = _load_board(day,'industries',http,warnings)
    intraday.extend(pts)
    concepts, pts = _load_board(day,'concepts',http,warnings)
    constituent_turnover(industries+concepts,quotes,halted,day)
    intraday.extend(pts)
    reasons = attempt('ths_hot_missing', lambda:hot_reasons(http, day), {})
    for r in rows:
        if r['code'] in reasons:
            r['reason'] = reasons[r['code']]
    for r in industries + concepts:
        if any(r['name'] in text for text in reasons.values()):
            attribution = '当日同花顺强势股归因涉及' + r['name']
            r['reason'] = f"{r['source']} · {attribution}" if r.get('source') else attribution
    pool = attempt('limit_pool_missing', lambda:limit_pool(http,'getTopicZTPool',day))
    prior = prior_session(day)
    previous = attempt('prior_limit_pool_missing', lambda:limit_pool(http,'getTopicZTPool',prior))
    broken = attempt('broken_pool_missing', lambda:limit_pool(http,'getTopicZBPool',day))
    down = attempt('limit_down_pool_missing', lambda:limit_pool(http,'getTopicDTPool',day))
    if pool is not None:
        breadth['limitUp'] = len(pool)
        if broken is not None and (len(broken) + len(pool)) > 0:
            breadth['brokenRate'] = len(broken) / (len(pool) + len(broken))
    if down is not None:
        breadth['limitDown'] = len(down)
    if previous and all(r['code'] in quotes for r in previous):
        breadth['yesterdayPremium'] = sum(quotes[r['code']]['pct'] for r in previous) / len(previous)
    elif previous is None or previous:
        comparison = attempt('prior_limit_comparison_missing', lambda:limit_pool(http,'getYesterdayZTPool',day))
        if comparison and (previous is None or {r['code'] for r in previous} == {r['code'] for r in comparison}):
            breadth['yesterdayPremium'] = sum(r['pct'] for r in comparison) / len(comparison)
        if comparison is not None and previous is None:
            # ylbc is the preceding session's height; zdp is today's return.
            previous = [dict(code=r['code'], name=r['name'], height=r['height'],
                             date=prior.isoformat()) for r in comparison]
            warnings.discard('prior_limit_pool_missing')
    return dict(date=day.isoformat(), stocks=rows, industries=industries, concepts=concepts, breadth=breadth,
                intraday=intraday, limitPool=pool, previousLimitPool=previous,
                marketComplete=complete, universeComplete=complete, coreExpected=len(core),
                coreQuotes=len(core & quotes.keys()),
                closeConfirmed=bool(rows or industries or concepts or any(p['time']=='15:00' for p in intraday)),
                warnings=sorted(warnings))
