"""Dated mainland cash-market observations for the local evening collector."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
import re

from market_calendar import calendar_data, is_session

BJ = timezone(timedelta(hours=8))
CLIST = 'https://push2.eastmoney.com/api/qt/clist/get'
KLINE = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
ALL_A = 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048'
BEIJING = 'm:0 t:81 s:2048'
TARGET_TIMES = {'09:25', '10:30', '13:30', '15:00'}


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def symbol(code):
    code = str(code).split('.')[0]
    if not re.fullmatch(r'\d{6}', code):
        return None
    if code.startswith(('60', '688', '689')):
        return code + '.SH'
    if code.startswith(('000', '001', '002', '003', '300', '301', '302')):
        return code + '.SZ'
    if code.startswith(('43', '83', '87', '88', '92')):
        return code + '.BJ'
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


def clist(http, scope, fields):
    """Stable security-code order; truncated, duplicate or changing pages invalidate the list."""
    rows, expected = {}, None
    for page in range(1, 151):
        obj = http.get_json(CLIST, params=dict(fs=scope, pn=page, pz=100, po=0, np=1,
                                               fid='f12', fltt=2, invt=2, fields=fields))
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
            sym = symbol(node.get('code') or node.get('sym'))
            if sym:
                ids.add(sym)
    return ids


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

    active = sorted((r for r in rows if r['amount'] >= 1e9 and
                     not re.search(r'ST|退', r['name'], re.I)), key=lambda r:(r['pct'], r['code']))
    for order in (active, reversed(active)):
        found = 0
        for row in order:
            if not row.get('listed') and len(checked) >= 80 and row['code'] not in checked:
                break
            listed = row.get('listed') or enrich(row).get('listedBefore')
            if listed and (day - date.fromisoformat(listed)).days >= 30:
                enrich(row)
                found += 1
                if found == 5:
                    break
    for row in rows:
        if row['code'] in core:
            enrich(row)


def board_history(http, code, day, frequency):
    obj = http.get_json(KLINE, params=dict(secid='90.' + code, klt=frequency, fqt=0,
                        end=day.strftime('%Y%m%d'), lmt=100 if frequency != 101 else 6,
                        fields1='f1,f2,f3,f4,f5,f6', fields2='f51,f52,f53,f54,f55,f56,f57'))
    data = obj['data']
    if data.get('code') != code:
        raise ValueError('board_identity')
    pairs = []
    for line in data['klines']:
        cells = line.split(',')
        close = number(cells[2])
        if close and close > 0:
            pairs.append((cells[0], close))
    return sorted(pairs)


def timed_points(pairs, name, day, prev):
    if prev is None or prev <= 0:
        return []
    points = []
    for stamp, price in pairs:
        if stamp[:10] == day.isoformat() and stamp[11:16] in TARGET_TIMES and price and price > 0:
            points.append(dict(date=day.isoformat(), time=stamp[11:16], name=name, pct=price / prev - 1))
    return points


def boards(http, scope, day, attempt):
    fields = 'f12,f14,f3,f6,f62,f124'
    raw = clist(http, scope, fields)
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
    rows.sort(key=lambda r:(r['pct'], r['code']))
    segments = []
    for row in {r['code']:r for r in rows[:5] + rows[-5:]}.values():
        bars = attempt('board_daily_missing', lambda:board_history(http, row['code'], day, 101), [])
        if not bars or bars[-1][0] != day.isoformat():
            continue
        row['spark'] = [v for _, v in bars[-5:]]
        if len(bars) >= 6:
            row['fiveDayReturn'] = bars[-1][1] / bars[-6][1] - 1
        if row is rows[-1] and len(bars) > 1:
            intraday = attempt('board_intraday_missing', lambda:board_history(http, row['code'], day, 5), [])
            segments.extend(timed_points(intraday, row['name'], day, bars[-2][1]))
    return rows, segments


def index_points(tdx, day, name, code):
    daily = dataframe_rows(tdx.index_bars(symbol=code, frequency=9, offset=45))
    prices = {str(r['datetime'])[:10]:number(r['close']) for r in daily}
    prev = prices.get(prior_session(day).isoformat())
    intraday = dataframe_rows(tdx.index_bars(symbol=code, frequency=0, offset=240))
    pairs = [(str(r['datetime']), number(r['close'])) for r in intraday]
    return timed_points(pairs, name, day, prev)


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


def collect_market(day, radar, http):
    warnings = set()

    def attempt(code, work, fallback=None):
        try:
            return work()
        except Exception:
            # Library exceptions can include gateway details. Emit only fixed codes.
            warnings.add(code)
            return fallback

    core = core_symbols(radar)
    tdx = attempt('tdx_unavailable', open_tdx)
    try:
        universe = {}
        if tdx is not None:
            for market in (0, 1):
                universe.update(attempt('tdx_inventory_incomplete', lambda:tdx_inventory(tdx, market), {}))
        bse = attempt('beijing_inventory_missing', lambda:_inventory_records(clist(http, BEIJING, 'f12,f26')), {})
        universe.update(bse)
        covered = bool({s[-2:] for s in universe} == {'SH','SZ','BJ'} and bse)
        em_rows = []
        em_fields = 'f12,f26,f14,f2,f3,f6,f8,f124'
        if not covered:
            em_rows = attempt('mainland_inventory_incomplete', lambda:clist(http, ALL_A, em_fields), [])
            fallback = attempt('unknown_mainland_code', lambda:_inventory_records(em_rows), {})
            if fallback:
                universe = fallback
                covered = {s[-2:] for s in universe} == {'SH','SZ','BJ'}
        requested = sorted(set(universe) | core)
        quotes = {}
        for start in range(0, len(requested), 60):
            ids = requested[start:start+60]
            url = 'https://qt.gtimg.cn/q=' + ','.join(tencent_id(s) for s in ids)
            text = attempt('tencent_batch_missing', lambda:http.get_text(url, encoding='gb18030'), '')
            quotes.update(quote_rows(text, set(ids), day))
        missing = universe.keys() - quotes.keys()
        halted = attempt('suspensions_missing', lambda:suspension_list(http, day), set()) if missing else set()
        # The TDX security master may still list a delisted security. When the
        # two sources disagree, reconcile against the fully paginated mainland
        # quote directory and use only individually dated closes as fallback.
        if missing - halted and not em_rows:
            em_rows = attempt('mainland_inventory_incomplete', lambda:clist(http, ALL_A, em_fields), [])
        if em_rows:
            official = attempt('unknown_mainland_code',lambda:_inventory_records(em_rows),{})
            fresh_rows = {r['code']:r for row in em_rows if (r := em_closed_stock(row, day))}
            if {s[-2:] for s in official} == {'SH','SZ','BJ'} and fresh_rows:
                universe = official
                covered = True
                for sym, row in fresh_rows.items():
                    quotes.setdefault(sym,row)
        for sym, row in quotes.items():
            row.update(universe.get(sym, {}))
        # No previous-date close, including a suspended stock, enters a ranking.
        complete = bool(covered and universe.keys() <= quotes.keys() | halted)
        if not complete:
            warnings.add('market_coverage_partial')
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
        if tdx is not None:
            for name, code in [('上证指数','000001'), ('创业板指','399006')]:
                intraday.extend(attempt('index_intraday_missing', lambda:index_points(tdx, day, name, code), []))
    finally:
        if tdx is not None:
            attempt('tdx_close_failed', tdx.close)

    industries, pts = attempt('industry_boards_missing', lambda:boards(http, 'm:90 t:2 f:!50', day, attempt), ([], []))
    intraday.extend(pts)
    concepts, pts = attempt('concept_boards_missing', lambda:boards(http, 'm:90 t:3 f:!50', day, attempt), ([], []))
    intraday.extend(pts)
    reasons = attempt('ths_hot_missing', lambda:hot_reasons(http, day), {})
    for r in rows:
        if r['code'] in reasons:
            r['reason'] = reasons[r['code']]
    for r in industries + concepts:
        if any(r['name'] in text for text in reasons.values()):
            r['reason'] = '当日同花顺强势股归因涉及' + r['name']
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
                marketComplete=complete, universeComplete=complete,
                closeConfirmed=bool(rows or industries or concepts or any(p['time']=='15:00' for p in intraday)),
                warnings=sorted(warnings))
