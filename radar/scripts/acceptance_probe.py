"""One bounded diagnostic execution; archives the exact gate-checked DATA.

No cache update or publication. Only an allowlisted, checked 10 MB archive is
written; raw HTTP bodies, cookies, crumbs, headers and credentials stay in memory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import build
import acceptance_bundle as bundle
import quotes
import yahoo_meta_close
from integrity import ZONES, financial_status, fresh_record, observation_time, valid_bars, pe_status, dated_fx, number
from market_calendar import context as calendar_context
from snapshot import CLOSED_QUOTE_STATES

ROOT = Path(__file__).resolve().parents[2]
MAX_REQUESTS = 240  # The 119 planned GETs and both retry paths share this budget.
TIMEOUT = 8
DEADLINE = 840  # 14 minutes; job 20 minutes, probe step 16 minutes.
MAX_BODY = 8 * 1024 * 1024
MAX_RECEIPT = 512 * 1024
DAILY_CLOSE_RETRY_INTERVAL = 60
DAILY_CLOSE_RETRY_LIMIT = 2
DAILY_CLOSE_RETRY_SECONDS = 240
HOSTS = {'query1.finance.yahoo.com', 'fc.yahoo.com', 'web.ifzq.gtimg.cn'}
DENIALS = {401, 403, 451}
SAFE_CODE = re.compile(r'^[A-Za-z0-9.^=_-]{1,40}$')


def utc():
    return dt.datetime.now(dt.UTC).isoformat()


class StopProbe(Exception):
    """Reason is a fixed internal code, never a server-provided message."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise StopProbe('redirect_not_followed')


class Budget:
    def __init__(self, limit=MAX_REQUESTS, seconds=DEADLINE):
        self.limit, self.count = limit, 0
        self.end = time.monotonic() + seconds
        self.denied = set()

    def take(self, lane, *, deadline=None):
        if lane in self.denied:
            raise StopProbe('access_refused_stop_path')
        end = self.end if deadline is None else min(self.end, deadline)
        remaining = end - time.monotonic()
        if self.count >= self.limit or remaining <= 0:
            raise StopProbe('request_or_time_budget_exhausted')
        self.count += 1
        return min(TIMEOUT, remaining)


def route(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname not in HOSTS | {'www.twse.com.tw'} or p.username is not None or p.password is not None or p.port not in (None, 443) or p.fragment:
        raise StopProbe('host_not_allowlisted')
    if p.hostname == 'www.twse.com.tw':
        query = urllib.parse.parse_qs(p.query, keep_blank_values=True)
        day = query.get('date', [''])[0]
        try:
            valid_day = dt.datetime.strptime(day, '%Y%m%d').strftime('%Y%m%d') == day
        except ValueError:
            valid_day = False
        if (p.path == '/rwd/zh/afterTrading/STOCK_DAY' and set(query) == {'date', 'stockNo', 'response'}
                and all(len(v) == 1 for v in query.values()) and valid_day
                and query['stockNo'] == ['2383'] and query['response'] == ['json']):
            return 'twse-close', 'stock-day'
        raise StopProbe('path_not_allowlisted')
    if p.hostname == 'fc.yahoo.com' and p.path in ('', '/'):
        return 'yahoo-valuation', 'cookie-seed'
    if p.hostname == 'query1.finance.yahoo.com':
        if p.path == '/v1/test/getcrumb': return 'yahoo-valuation', 'crumb'
        if p.path == '/v7/finance/quote': return 'yahoo-valuation', 'quote'
        if p.path.startswith('/v8/finance/chart/'): return 'yahoo-chart', 'chart'
    if p.hostname == 'web.ifzq.gtimg.cn' and p.path == '/appstock/app/fqkline/get':
        return 'tencent-kline', 'kline'
    raise StopProbe('path_not_allowlisted')


class ProbeHttp(quotes.Http):
    def __init__(self, budget, source, *, retry_429=True, deadline=None):
        self.budget, self.source = budget, source
        self.retry_429 = retry_429
        self.deadline = budget.end if deadline is None else min(budget.end, deadline)
        self.events, self.documents, self.batches = [], [], []
        self._crumb = None
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())
        self.op.addheaders = [('User-Agent', quotes.UA), ('Accept', 'application/json,text/plain,*/*')]

    def get(self, url, tries=1):
        lane, path = route(url)
        if not lane.startswith(self.source):
            raise StopProbe('separate_source_only')
        host = urllib.parse.urlsplit(url).hostname
        for attempt in range(2 if self.retry_429 else 1):
            timeout = self.budget.take(lane, deadline=self.deadline)
            event = {'host': host, 'pathClass': path, 'attempt': attempt+1, 'startedAt': utc()}
            self.events.append(event)
            try:
                with self.op.open(url, timeout=timeout) as response:
                    raw = response.read(MAX_BODY+1)
                    event.update(httpStatus=response.status, status='connected', bytes=len(raw), receivedAt=utc())
                if time.monotonic() > self.deadline:
                    raise StopProbe('request_or_time_budget_exhausted')
                if len(raw) > MAX_BODY:
                    raise StopProbe('response_too_large')
                if path not in ('crumb', 'cookie-seed'):
                    event['sha256'] = hashlib.sha256(raw).hexdigest()
                return raw
            except urllib.error.HTTPError as exc:
                event.update(httpStatus=exc.code, status='http_error', receivedAt=utc())
                if exc.code in DENIALS:
                    self.budget.denied.add(lane)
                    raise StopProbe('access_refused_stop_path') from None
                # fc.yahoo.com's documented cookie-seeding 404 is not an auth denial.
                if path == 'cookie-seed' and exc.code == 404:
                    event['status'] = 'cookie_seed_404'
                    return b''
                if exc.code == 429 and attempt == 0 and self.retry_429:
                    retry = exc.headers.get('Retry-After', '5')
                    try:
                        delay = float(retry)
                    except (TypeError, ValueError):
                        # Do not shorten an HTTP-date or unknown server delay.
                        delay = 11
                    if 0 <= delay <= 10 and time.monotonic()+delay < self.deadline:
                        event['retryAfterSeconds'] = delay
                        time.sleep(delay)
                        continue
                raise StopProbe('http_error_no_more_retries') from None
            except StopProbe:
                event['status'] = 'stopped'
                raise
            except Exception:
                event['status'] = 'transport_error'
                raise StopProbe('transport_error_no_retry') from None
        raise StopProbe('retry_limit')

    def json(self, url, tries=1):
        try:
            value = json.loads(self.get(url).decode('utf-8'))
        except (ValueError, UnicodeError):
            raise StopProbe('json_parse_failed') from None
        self.documents.append(value)
        return value

    def yahoo(self, path, tries=1):
        # Explicit primary only. Never switch to query2 following an access refusal.
        if path.startswith('/v7/finance/quote?'):
            symbols = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query).get('symbols', [''])[0].split(',')
            start, docs = len(self.events), len(self.documents)
            batch = {'batch':len(self.batches)+1,'requested':len(symbols)}
            self.batches.append(batch)
            try:
                return self.json(quotes.YH[0]+path)
            finally:
                events=self.events[start:]
                batch.update(attempts=len(events),connection=any(e.get('httpStatus')==200 for e in events),
                             parse=len(self.documents)>docs)
        return self.json(quotes.YH[0]+path)

    def crumb(self):
        if self._crumb is None:
            self.get('https://fc.yahoo.com')
            value = self.get(quotes.YH[0]+'/v1/test/getcrumb').decode('utf-8').strip()
            if not value or '<' in value or len(value) > 256:
                raise StopProbe('crumb_invalid')
            self._crumb = value
        return self._crumb


def chart_meta(h):
    for doc in reversed(h.documents):
        if isinstance(doc, dict):
            result = (doc.get('chart') or {}).get('result')
            if isinstance(result, list) and result and isinstance(result[0], dict):
                return result[0].get('meta') or {}
    return {}


def date_ok(value):
    try:
        return dt.date.fromisoformat(value).isoformat() == value
    except (TypeError, ValueError):
        return False


def daily_quality(value, h, company, *, calendar_policy=False, clock=None):
    b = value.get('bars', [])
    valid = valid_bars(b)
    meta = chart_meta(h)
    zone = meta.get('exchangeTimezoneName')
    try:
        timezone_ok = bool(zone) and ZoneInfo(zone).utcoffset(dt.datetime.now()) == ZoneInfo(ZONES[company['mkt']]).utcoffset(dt.datetime.now())
    except (KeyError, ValueError, TypeError):
        timezone_ok = False
    first, last = (b[0][0], b[-1][0]) if valid else (None, None)
    enough = valid and len(b) >= 120 and (dt.date.fromisoformat(last)-dt.date.fromisoformat(first)).days >= 731
    m = build.metrics(b) if valid else {}
    fields = {'validBars': valid, 'adjustmentComplete': valid and all(quotes.positive(x[2]) for x in b),
              'high52Available': m.get('hi52') is not None, 'historySufficient': bool(enough),
              'currencyMatches': value.get('currency') == company['cur'], 'timezoneValidAndOffsetMatches': timezone_ok,
              'dateFresh': bool(last and fresh_record(value, clock or dt.datetime.now(dt.UTC), last, company['mkt'],
                  symbol=company['sym'] if calendar_policy else None, allow_intraday=calendar_policy, phase=value.get('phase','unknown')))}
    # Tencent cannot prove currency/timezone/closed; never inherit Yahoo's metadata.
    return fields, {'count': len(b), 'firstDate': first, 'asOf': last,
                    'adjustedCount': sum(quotes.positive(x[2]) for x in b) if valid else 0,
                    'highCount': sum(quotes.positive(x[3]) for x in b) if valid else 0,
                    'phase': value.get('phase', 'unknown'), 'receivedAt':value.get('receivedAt'), 'currencyMatches': fields['currencyMatches'],
                    'timezonePresent': bool(zone)}, value.get('phase') == 'closed'


def index_quality(value, h, *, symbol=None, clock=None):
    fields = {'positivePrice': quotes.positive(value.get('price')), 'changePresent': build.number(value.get('chg')),
              'dateValid': date_ok(value.get('date')),
              'dateFresh': fresh_record(value, clock or dt.datetime.now(dt.UTC), value.get('date'), symbol=symbol,
                  allow_intraday=bool(symbol), phase=value.get('phase','unknown')) if value.get('date') else False}
    return fields, {'count': 1 if fields['positivePrice'] else 0, 'asOf': value.get('date') if fields['dateValid'] else None,
                    'receivedAt':value.get('receivedAt'),'phase': value.get('phase', 'unknown')}, value.get('phase') == 'closed'


def fx_quality(value, h, currency):
    history = value.get('rates') or []
    price = history[-1][2] if history else None
    fields = {'positiveRate': quotes.positive(value.get('value')), 'sourcePricePresent': quotes.positive(price),
              'directionVerified': quotes.positive(price) and value.get('value') == (1/price if currency == 'EUR' else price),
              'dateValid': date_ok(value.get('asOf')),
              'finalDailyHistoryConfirmed': dated_fx(value, currency, value.get('asOf'), dt.datetime.now(dt.UTC)) is not None,
              'dateFresh': fresh_record(value, dt.datetime.now(dt.UTC), value.get('asOf')) if value.get('asOf') else False}
    return fields, {'count': len(history), 'asOf': value.get('asOf'), 'dates': [r[0] for r in history],
                    'direction': 'USD-to-local', 'inverted': currency == 'EUR'}, True


def month_quality(value, h, *, symbol=None, clock=None):
    b = value.get('bars', [])
    current = observation_time('ratio', value)
    ratio = build.ratio_block(b, [[m, 1.] for m, _ in b]) if b else None
    fields = {'history120Completed': bool(ratio and ratio['completedMonths'] >= 120),
              'currentDated': current is not None,
              'dateFresh': bool(current and fresh_record(value, clock or dt.datetime.now(dt.UTC), value['asOf'],symbol=symbol,allow_intraday=bool(symbol),phase='unknown'))}
    return fields, {'count': len(b), 'completedMonths': ratio['completedMonths'] if ratio else 0,
                    'asOf': value.get('asOf'), 'currentDated': current is not None}, current is not None


def inspect(category, code, source, budget, fetch, quality, *, retry_deadline=None):
    if not SAFE_CODE.fullmatch(code): raise StopProbe('unexpected_config_code')
    h = (ProbeHttp(budget, source) if retry_deadline is None
         else ProbeHttp(budget, source, retry_429=False, deadline=retry_deadline))
    row = {'category': category, 'code': code, 'source': source, 'startedAt': utc(),
           'connection': False, 'parse': False, 'quality': False, 'publicationGate': False,
           'checks': {}, 'details': {}, 'failure': None}
    value = None
    try:
        value = fetch(h)
        row['parse'] = bool(h.documents)
        fields, details, gate = quality(value, h)
        row.update(checks=fields, details=details, quality=all(fields.values()))
        row['publicationGate'] = row['quality'] and bool(gate)
    except Exception as exc:
        row['failure'] = str(exc) if isinstance(exc, (StopProbe, quotes.SourceDataError)) else type(exc).__name__
        if isinstance(exc, quotes.SourceDataError): row['details']['count'] = exc.count
        # No server exception text, URLs, local paths, response fields, cookies or crumb.
        row['parse'] = bool(h.documents) and not (isinstance(exc, StopProbe) and str(exc) == 'json_parse_failed')
    row['connection'] = any(e.get('httpStatus') == 200 for e in h.events)
    row['requests'] = h.events
    row['finishedAt'] = utc()
    return row, value


def inventory(data):
    companies = [{k: c[k] for k in ('sym', 'mkt', 'cur')} for c in data['companies']]
    return companies, [c for c in companies if c['mkt'] in ('A股', '港股') and quotes.tencent_code(c['sym'])], sorted({c['cur'] for c in companies}-{'USD'})


def access_affects(item, access):
    """A denied daily endpoint cannot explain an unrelated missing PE field."""
    category=access['category']
    if item['kind']=='company':
        metric=item.get('metric')
        if category=='quote-session':return metric in ('price','PE','marketCap','marketCapUSD')
        return (access.get('symbol')==item.get('symbol') and category in ('company-yahoo-daily', 'company-yahoo-daily-retry', 'company-twse-close-proof')
                and metric in ('price','daily','r5','r20','r60','ytd','high52'))
    if item['kind']=='ratio':return category=='ratio-tencent'
    return (access.get('symbol')==item.get('symbol') and
            (category.startswith('index-') if item['kind']=='index' else category=='fx'))


def company_yahoo_daily(h, symbol, budget, rows, evidence, snapshot_clock):
    try:
        value = quotes.yahoo_daily(h, symbol)
    finally:
        if evidence is not None and h.documents:
            event = next((item for item in reversed(h.events) if item.get('httpStatus') == 200), None)
            received = event.get('receivedAt') if event else None
            chart = yahoo_meta_close.chart_evidence(h.documents[-1], symbol, received) if received else None
            if chart is not None:
                evidence[symbol] = chart
    if evidence is None or symbol != '2383.TW' or value.get('phase') != 'unknown':
        return value
    if chart_meta(h).get('symbol') != '2383.TW':
        return value
    from equity_close_proof import make_proof
    current = snapshot_clock or dt.datetime.now(dt.UTC)
    expected = calendar_context(symbol, current)['expectedCompletedDate']
    if not expected or value.get('asOf') != expected:
        return value
    closing = dt.datetime.fromisoformat(expected + 'T13:30:00+08:00')
    if current < closing or value.get('currency') != 'TWD' or value.get('timezone') != 'Asia/Taipei':
        return value
    official = ProbeHttp(budget, 'twse') if h.retry_429 else ProbeHttp(budget, 'twse', deadline=h.deadline)
    official_url = ('https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date='
                    + expected.replace('-', '') + '&stockNo=2383&response=json')
    extra = {'category': 'company-twse-close-proof', 'code': symbol, 'source': 'twse',
             'connection': False, 'parse': False, 'quality': False, 'publicationGate': False,
             'checks': {}, 'details': {}, 'failure': None, 'startedAt': utc()}
    try:
        document = official.json(official_url)
        extra['parse'] = True
        source_event = next(e for e in reversed(h.events) if e.get('httpStatus') == 200 and e.get('sha256'))
        yahoo_url = ('https://query1.finance.yahoo.com/v8/finance/chart/2383.TW'
                     '?range=5y&interval=1d&includeAdjustedClose=true')
        proof = make_proof(value, document,
            official_event={**official.events[-1], 'sourceUrl': official_url},
            yahoo_event={**source_event, 'sourceUrl': yahoo_url}, expected_day=expected,
            now=snapshot_clock or dt.datetime.now(dt.UTC),
            execution={k: os.environ.get(k, '') for k in ('GITHUB_SHA', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')})
        extra.update(quality=proof is not None, publicationGate=proof is not None,
                     checks={'independentCloseProof': proof is not None})
        if proof is not None:
            value = {**value, 'independentCloseProof': proof}
    except Exception as exc:
        extra['failure'] = str(exc) if isinstance(exc, StopProbe) else 'official_close_proof_failed'
    extra.update(connection=any(e.get('httpStatus') == 200 for e in official.events),
                 requests=official.events, finishedAt=utc())
    rows.append(extra)
    return value


def retry_missing_daily(companies, daily, evidence, rows, budget, snapshot_clock):
    """Re-read all affected stocks in bounded rounds before taking a snapshot close."""
    def now():
        return snapshot_clock or dt.datetime.now(dt.UTC)

    pending = [company for company in companies if yahoo_meta_close.missing_close(
        daily.get(company['sym']), evidence.get(company['sym']), company['sym'], now())]
    deadline = min(budget.end, time.monotonic() + DAILY_CLOSE_RETRY_SECONDS)
    reconfirmed = {}
    lane = 'yahoo-chart'
    for _ in range(DAILY_CLOSE_RETRY_LIMIT):
        if (not pending or lane in budget.denied or budget.count >= budget.limit
                or time.monotonic() + DAILY_CLOSE_RETRY_INTERVAL + TIMEOUT > deadline):
            break
        time.sleep(DAILY_CLOSE_RETRY_INTERVAL)
        next_round = []
        for company in pending:
            if lane in budget.denied or budget.count >= budget.limit or time.monotonic() + TIMEOUT > deadline:
                break
            symbol = company['sym']
            observed = {}
            row, value = inspect('company-yahoo-daily-retry', symbol, 'yahoo', budget,
                lambda h: company_yahoo_daily(h, symbol, budget, rows, observed, snapshot_clock),
                lambda v, h: daily_quality(v, h, company, calendar_policy=True, clock=snapshot_clock),
                retry_deadline=deadline)
            rows.append(row)
            reconfirmed.pop(symbol, None)
            if symbol not in observed:
                continue
            evidence[symbol] = observed[symbol]
            previous = daily.get(symbol)
            checked_at = now()
            still_missing = yahoo_meta_close.missing_close(value, observed[symbol], symbol, checked_at)
            expected = calendar_context(symbol, checked_at)['expectedCompletedDate']
            recovered = value and any(bar[0] == expected for bar in value['bars'])
            if value and (not previous or value['asOf'] >= previous['asOf'] or recovered):
                daily[symbol] = value
            if row['failure'] in (None, 'yahoo_chart_empty_daily_bars') and still_missing:
                next_round.append(company)
                if value:
                    reconfirmed[symbol] = value
        pending = next_round
    if lane not in budget.denied:
        for company in companies:
            symbol = company['sym']
            if symbol in reconfirmed:
                value = reconfirmed[symbol]
                supplemented = yahoo_meta_close.supplement(value, evidence[symbol], company, now())
                if supplemented is not value:
                    daily[symbol] = supplemented


def collect(data, budget, market_sink=None, *, snapshot_sink=None, snapshot_clock=None, calendar_policy=False,
            daily_baseline=None):
    companies, tencent, currencies = inventory(data)
    rows = []
    mk = {k: {} for k in ('daily', 'quote', 'index', 'fx', 'ratio')}
    evidence = {} if calendar_policy else None
    for source, group, category in (('yahoo', companies, 'company-yahoo-daily'), ('tencent', tencent, 'company-tencent-backup')):
        for c in group:
            def fetch_daily(h):
                if source == 'yahoo':
                    return company_yahoo_daily(h, c['sym'], budget, rows, evidence, snapshot_clock)
                return quotes.tencent_daily(h, c['sym'])
            row, value = inspect(category, c['sym'], source, budget, fetch_daily,
                lambda v,h: daily_quality(v,h,c,calendar_policy=calendar_policy,clock=snapshot_clock))
            rows.append(row)
            if source == 'yahoo' and value: mk['daily'][c['sym']] = value
    # The adapter executes exactly its configured 40+2 batches, with one cookie jar.
    h = ProbeHttp(budget, 'yahoo')
    quote_failure = None
    try:
        values = quotes.yahoo_quotes(h, [c['sym'] for c in companies])
    except Exception as exc:
        values = {}
        quote_failure = str(exc) if isinstance(exc, StopProbe) else type(exc).__name__
    mk['quote'] = values
    for i,c in enumerate(companies):
        batch=h.batches[i//40] if i//40<len(h.batches) else {}
        v = values.get(c['sym'], {})
        observed = observation_time('quote', v)
        d = observed.astimezone(ZoneInfo(ZONES[c['mkt']])).date().isoformat() if observed else None
        fields = {'marketCap': quotes.positive(v.get('marketCap')), 'trailingPE': quotes.positive(v.get('trailingPE')),
                  'price': quotes.positive(v.get('regularMarketPrice')),
                  'closedMarketState': v.get('marketState') in CLOSED_QUOTE_STATES,
                  'sourceTime': observed is not None, 'currencyMatches': v.get('currency') == c['cur'],
                  'dateMatchesDaily': bool(d and d == mk['daily'].get(c['sym'],{}).get('asOf')),
                  'dateFresh': bool(d and fresh_record(v,snapshot_clock if snapshot_clock is not None else dt.datetime.now(dt.UTC),d,c['mkt'],
                      symbol=c['sym'] if calendar_policy else None,allow_intraday=calendar_policy,phase=build.latest.quote_phase(v)))}
        selected=build.latest.select_quote(v,None,c['mkt'],c['cur'],snapshot_clock if snapshot_clock is not None else dt.datetime.now(build.BJ),symbol=c['sym'] if calendar_policy else None)[0]
        eps=v.get('epsTrailingTwelveMonths')
        not_applicable=v.get('trailingPE') is None and number(eps) and eps<=0
        quality=bool(selected) and fields['marketCap'] and fields['price'] and (fields['trailingPE'] or not_applicable)
        rows.append({'category':'company-yahoo-quote','code':c['sym'],'source':'yahoo',
                     'connection':bool(batch.get('connection')), 'parse':bool(batch.get('parse')),
                     'quality':quality, 'publicationGate':quality,
                     'checks':fields,'details':{'count':int(bool(v)),'asOf':d,'observedAt':observed.isoformat() if observed else None,
                                              'receivedAt':v.get('receivedAt'), 'peStatus':'not_meaningful' if not_applicable else pe_status(v.get('trailingPE')),
                                              'marketState':v.get('marketState') if v.get('marketState') in (*CLOSED_QUOTE_STATES, 'REGULAR') else 'unknown'},'requests':[]})
    quote_session = {'failure':quote_failure,'requests':h.events,'batches':h.batches,'expectedBatchSizes':[len(companies[i:i+40]) for i in range(0,len(companies),40)],'returned':len(values),
                     'cookieAvailable':bool(list(h.jar)),'crumbAvailable':bool(h._crumb)}
    for x in data['config']['indices']:
        for source in ('yahoo', 'tencent') if x.get('tencent') else ('yahoo',):
            row,value = inspect('index-'+source, x['symbol'],source,budget,
                                lambda h: quotes.index_quote(h,x['symbol'],x.get('tencent',''),source=source),
                                lambda v,h: index_quality(v,h,symbol=x['symbol'] if calendar_policy else None,clock=snapshot_clock))
            rows.append(row)
            previous=mk['index'].get(x['symbol'])
            if value and build.latest.select_index(value,None,snapshot_clock if snapshot_clock is not None else dt.datetime.now(build.BJ),symbol=x['symbol'] if calendar_policy else None) and (not previous or value.get('date','')>previous.get('date','')):
                mk['index'][x['symbol']] = value
    for cur in currencies:
        row,value=inspect('fx',cur,'yahoo',budget,lambda h:quotes.fx(h,cur),lambda v,h:fx_quality(v,h,cur))
        rows.append(row)
        if value: mk['fx'][cur]=value
    cfg=data['config']['ratio']
    for key, prefix in (('cyb','growth'),('hl','dividend')):
        for source in ('tencent','yahoo'):
            row,value=inspect('ratio-'+source,key,source,budget,
                lambda h:quotes.monthly(h,cfg[prefix+'_tencent'],cfg[prefix+'_yahoo']),
                lambda v,h:month_quality(v,h,symbol=cfg[prefix+'_yahoo'] if calendar_policy else None,clock=snapshot_clock))
            rows.append(row)
            if source=='tencent' and value: mk['ratio'][key]=value
    if calendar_policy:
        retry_missing_daily(companies, mk['daily'], evidence, rows, budget, snapshot_clock)
        if market_sink is not None:
            market_sink['dailyEvidence'] = evidence
        for row in rows:
            if row['category'] == 'company-yahoo-quote':
                day = row['details']['asOf']
                row['checks']['dateMatchesDaily'] = bool(day and day == mk['daily'].get(row['code'], {}).get('asOf'))
    # Freeze once AFTER the last source result: receivedAt must not be in the
    # future relative to this clock. Transport event times remain actual times.
    fixed_clock = snapshot_clock if snapshot_clock is not None else dt.datetime.now(build.BJ)
    if calendar_policy:
        carry = {}
        if daily_baseline is not None:
            transport = {row['code']: row for row in rows
                         if row['category'] in ('company-yahoo-daily', 'company-yahoo-daily-retry')}
            carry = {'daily_baseline': daily_baseline, 'daily_evidence': evidence, 'daily_transport': transport}
        D,stale,missing=build.assemble(data,mk,mk,fixed_clock,calendar_policy=True,**carry)
    else:
        D,stale,missing=build.assemble(data,mk,mk,fixed_clock)
    # Expose transport denial separately from empty/partial observations.
    D['meta']['sourceAccess']=[{'category':r['category'],'symbol':r['code'],'source':r['source'],'status':'access_blocked'} for r in rows if r.get('failure')=='access_refused_stop_path' or any(e.get('httpStatus') in DENIALS for e in r.get('requests',[]))]
    if any(e.get('httpStatus') in DENIALS for e in h.events):
        D['meta']['sourceAccess'].append({'category':'quote-session','source':'yahoo','status':'access_blocked'})
    for item in D['meta'].get('coverage',[]):
        if item['status']=='missing' and any(access_affects(item,a) for a in D['meta']['sourceAccess']):
            item.update(status='access_blocked',reason='explicit_source_access_refusal')
    gates={'blockers':build.release_blockers(D),'missingDailyCount':len(missing),'staleDailyCount':len(stale),
           'snapshot':D['meta']['snapshot'],
           'marketCapAvailable':sum(c['mcapUSD'] is not None for c in D['companies']),
           'peAvailable':sum(c['pe'] is not None for c in D['companies']),
           'asOf':D['meta']['asOf'],'asOfByMarket':D['meta']['asOfByMarket'], 'ratioAvailable':D['ratio'] is not None,
           'financialVerified':sum(financial_status(c.get('financial'),fixed_clock.date(),c)=='verified' for c in data['companies']),
           'financialPartial':sum(financial_status(c.get('financial'),fixed_clock.date(),c)=='verified_partial' for c in data['companies']),
           'financialRequired':len(companies),'primaryOnlyAssembly':False,
           'indexAssemblySources':{k:v.get('src') for k,v in mk['index'].items()},
           'coverage':D['meta'].get('coverage',[]),
           'dataSHA256':bundle.data_digest(D)}
    summary={}
    for category in sorted({r['category'] for r in rows}):
        group=[r for r in rows if r['category']==category]
        summary[category]={'planned':len(group),**{k:sum(bool(r[k]) for r in group) for k in ('connection','parse','quality','publicationGate')}}
    if market_sink is not None:
        market_sink.update(mk)
    if snapshot_sink is not None:
        snapshot_sink.update(data=D, clock=fixed_clock, gates=gates)
    return rows,summary,quote_session,gates


def offline_test_ids():
    """Discover trusted identifiers without executing tests or exposing errors."""
    import unittest
    try:
        loader = unittest.TestLoader()
        pending = [loader.discover(str(ROOT / 'radar/tests'))]
        if loader.errors:
            return frozenset()
        identifiers = set()
        while pending:
            item = pending.pop()
            if isinstance(item, unittest.TestSuite):
                pending.extend(item)
            elif isinstance(item, unittest.TestCase):
                identifiers.add(item.id())
        return frozenset(identifiers)
    except Exception:
        return frozenset()


def offline_failure_summary(output, count, allowed_ids):
    """Expose only bounded test identifiers, never captured traceback content."""
    failed = re.findall(r'^(?:FAIL|ERROR): (test_[A-Za-z0-9_]{1,100}) \((test_[A-Za-z0-9_.]{1,200})\)\r?$',
                        output, re.M)
    return {'fatal': 'offline_tests_failed', 'tests': count,
            'failedTests': list(dict.fromkeys(identifier for _, identifier in failed
                                             if identifier in allowed_ids))[:50],
            'rawOutputOmitted': True}


def preflight():
    from research_snapshot import ResearchAbort

    clock = dt.datetime.now(build.BJ)
    try:
        config = build.research_config()
        build.load_notion_contract(config)
    except (OSError, ValueError, ResearchAbort) as error:
        raise StopProbe('schema_errors') from error
    _,report=build.validate_market_config(config, clock.date())
    if report.errors: raise StopProbe('schema_errors')
    proc=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','radar/tests','-v'],cwd=ROOT,capture_output=True)
    output=(proc.stdout+proc.stderr).decode('utf-8','replace')
    match=re.search(r'Ran (\d+) tests?',output)
    count=int(match[1]) if match else 0
    if proc.returncode or count<55:
        print(json.dumps(offline_failure_summary(output, count, offline_test_ids())), file=sys.stderr)
        raise StopProbe('offline_tests_failed')
    return {'tests':count,'schemaWarnings':len(report.warnings),'schemaErrors':len(report.errors)}


def diagnostic_research(config):
    """Use the checked-in Notion sample for a probe without Notion credentials."""
    import tempfile

    sys.path.append(str(ROOT / 'radar/tests'))
    try:
        from notion_fixtures import FakeTransport, FixtureSet

        with tempfile.TemporaryDirectory(prefix='radar-interface-') as directory:
            fixture = FixtureSet(Path(directory))
            transport = FakeTransport(fixture)
            return build.load_research(
                transport=transport, token=fixture.env['NOTION_TOKEN'],
                fixed_clock=fixture.clock, config=config, sleep=transport.sleep, pace=transport.pace)
    finally:
        sys.path.pop()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--preflight',action='store_true')
    ap.add_argument('--out',type=Path,help='receipt.json within a new archive directory')
    ap.add_argument('--verify-bundle',type=Path,help='read-only offline archive verification')
    args=ap.parse_args()
    if args.verify_bundle:
        print(json.dumps(bundle.verify_bundle(args.verify_bundle)))
        return 0
    if args.preflight:
        print(json.dumps(preflight()))
        return 0
    if not args.out: ap.error('--out required')
    if args.out.name != 'receipt.json': ap.error('--out must name receipt.json')
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('GITHUB_RUN_ATTEMPT')!='1':
        raise StopProbe('github_first_attempt_only')
    clock = dt.datetime.now(build.BJ)
    config = build.research_config()
    data,rep=build.validate_market_config(config, clock.date())
    if rep.errors: raise StopProbe('schema_errors')
    research, fetched = diagnostic_research(config)
    data.update(industries=research['industries'], chokepoints=research['chokepoints'], companies=research['companies'])
    receipt={'schemaVersion':1,'purpose':'interface-acceptance-not-publication','startedAt':utc(),
             'execution':{k:os.environ.get(k) for k in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','RUNNER_OS','RUNNER_ARCH','ImageOS','ImageVersion')},
             'python':platform.python_version(),'kernel':platform.release(),
             'limits':{'requests':MAX_REQUESTS,'timeoutSeconds':TIMEOUT,'deadlineSeconds':DEADLINE,'attemptsPerGet':2,'retryOnly429':True,'maxRetryAfterSeconds':10},
             'schemaWarnings':len(rep.warnings),'researchInput':'notion-fixture',
             'fallbackPolicy':'separate-source-only; query2 not attempted; access denials stop corresponding lane'}
    budget=Budget()
    snapshot = {}
    rows,summary,session,gates=collect(data,budget,snapshot_sink=snapshot)
    fixed_clock = snapshot['clock']
    research, _ = build.load_research(transport=None, token=None, fixed_clock=fixed_clock,
                                      config=config, fetch=fetched)
    archived = snapshot['data']
    access_blocked = {(item['kind'], item['symbol'], item.get('metric'))
                      for item in archived['meta']['coverage'] if item['status'] == 'access_blocked'}
    archived.update(build.apply_research(archived, research, fixed_clock, config))
    meta = archived['meta']
    # Diagnostic fixture research cannot provide a production last-good snapshot.
    del meta['notion']
    meta['diagnosticResearchSource'] = 'notion-fixture'
    meta['reviewPreview'] = True
    for item in meta['coverage']:
        key = item['kind'], item['symbol'], item.get('metric')
        if key in access_blocked and item['status'] == 'missing':
            item.update(status='access_blocked', reason='explicit_source_access_refusal')
    evidence = [(company['provenance'].get('financial') or {}).get('evidence') for company in archived['companies']]
    gates.update(blockers=build.release_blockers(archived), dataSHA256=bundle.data_digest(archived),
                 coverage=meta['coverage'], financialRequired=len(evidence),
                 financialVerified=evidence.count('source'), financialPartial=evidence.count('partial'))
    receipt.update(results=rows,summary=summary,quoteSession=session,publication=gates,
                   requestsMade=budget.count,deniedPaths=sorted(budget.denied),finishedAt=utc(),
                   fixedClock=fixed_clock.isoformat())
    saved = bundle.write_bundle(args.out.parent, archived, receipt, fixed_clock)
    print(json.dumps({'archive':saved,'summary':summary,
                      'publicationBlocked':bool(gates['blockers']),'publicationAuthorized':False,
                      'requestsMade':budget.count}))
    return 0  # Completed diagnostics, NOT a claim that interfaces or release gates passed.


if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'fatal':str(exc) if isinstance(exc,(StopProbe,bundle.BundleError)) else type(exc).__name__}))
        sys.exit(2)
