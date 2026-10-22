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
from integrity import ZONES, financial_status, fresh_record, observation_time, valid_bars, pe_status, dated_fx, number
from snapshot import CLOSED_QUOTE_STATES

ROOT = Path(__file__).resolve().parents[2]
MAX_REQUESTS = 240  # 119 planned GETs, at most one 429 retry each; 2 spare.
TIMEOUT = 8
DEADLINE = 840  # 14 minutes; job 20 minutes, probe step 16 minutes.
MAX_BODY = 8 * 1024 * 1024
MAX_RECEIPT = 512 * 1024
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

    def take(self, lane):
        if lane in self.denied:
            raise StopProbe('access_refused_stop_path')
        if self.count >= self.limit or time.monotonic() >= self.end:
            raise StopProbe('request_or_time_budget_exhausted')
        self.count += 1
        return max(.1, min(TIMEOUT, self.end - time.monotonic()))


def route(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443):
        raise StopProbe('host_not_allowlisted')
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
    def __init__(self, budget, source):
        self.budget, self.source = budget, source
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
        for attempt in range(2):
            timeout = self.budget.take(lane)
            event = {'host': host, 'pathClass': path, 'attempt': attempt+1, 'startedAt': utc()}
            self.events.append(event)
            try:
                with self.op.open(url, timeout=timeout) as response:
                    raw = response.read(MAX_BODY+1)
                    event.update(httpStatus=response.status, status='connected', bytes=len(raw), receivedAt=utc())
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
                if exc.code == 429 and attempt == 0:
                    retry = exc.headers.get('Retry-After', '5')
                    try:
                        delay = float(retry)
                    except (TypeError, ValueError):
                        # Do not shorten an HTTP-date or unknown server delay.
                        delay = 11
                    if 0 <= delay <= 10 and time.monotonic()+delay < self.budget.end:
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


def daily_quality(value, h, company):
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
              'dateFresh': bool(last and fresh_record(value, dt.datetime.now(dt.UTC), last, company['mkt']))}
    # Tencent cannot prove currency/timezone/closed; never inherit Yahoo's metadata.
    return fields, {'count': len(b), 'firstDate': first, 'asOf': last,
                    'adjustedCount': sum(quotes.positive(x[2]) for x in b) if valid else 0,
                    'highCount': sum(quotes.positive(x[3]) for x in b) if valid else 0,
                    'phase': value.get('phase', 'unknown'), 'receivedAt':value.get('receivedAt'), 'currencyMatches': fields['currencyMatches'],
                    'timezonePresent': bool(zone)}, value.get('phase') == 'closed'


def index_quality(value, h):
    fields = {'positivePrice': quotes.positive(value.get('price')), 'changePresent': build.number(value.get('chg')),
              'dateValid': date_ok(value.get('date')),
              'dateFresh': fresh_record(value, dt.datetime.now(dt.UTC), value.get('date')) if value.get('date') else False}
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


def month_quality(value, h):
    b = value.get('bars', [])
    current = observation_time('ratio', value)
    ratio = build.ratio_block(b, [[m, 1.] for m, _ in b]) if b else None
    fields = {'history120Completed': bool(ratio and ratio['completedMonths'] >= 120),
              'currentDated': current is not None,
              'dateFresh': bool(current and fresh_record(value, dt.datetime.now(dt.UTC), value['asOf']))}
    return fields, {'count': len(b), 'completedMonths': ratio['completedMonths'] if ratio else 0,
                    'asOf': value.get('asOf'), 'currentDated': current is not None}, current is not None


def inspect(category, code, source, budget, fetch, quality):
    if not SAFE_CODE.fullmatch(code): raise StopProbe('unexpected_config_code')
    h = ProbeHttp(budget, source)
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
        return (access.get('symbol')==item.get('symbol') and category=='company-yahoo-daily'
                and metric in ('price','daily','r5','r20','r60','ytd','high52'))
    if item['kind']=='ratio':return category=='ratio-tencent'
    return (access.get('symbol')==item.get('symbol') and
            (category.startswith('index-') if item['kind']=='index' else category=='fx'))


def collect(data, budget, market_sink=None, *, snapshot_sink=None, snapshot_clock=None):
    companies, tencent, currencies = inventory(data)
    rows = []
    mk = {k: {} for k in ('daily', 'quote', 'index', 'fx', 'ratio')}
    for source, group, category in (('yahoo', companies, 'company-yahoo-daily'), ('tencent', tencent, 'company-tencent-backup')):
        for c in group:
            fn = quotes.yahoo_daily if source == 'yahoo' else quotes.tencent_daily
            row, value = inspect(category, c['sym'], source, budget, lambda h: fn(h, c['sym']), lambda v,h: daily_quality(v,h,c))
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
                  'dateFresh': bool(d and fresh_record(v,snapshot_clock if snapshot_clock is not None else dt.datetime.now(dt.UTC),d,c['mkt']))}
        selected=build.latest.select_quote(v,None,c['mkt'],c['cur'],snapshot_clock if snapshot_clock is not None else dt.datetime.now(build.BJ))[0]
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
                                lambda h: quotes.index_quote(h,x['symbol'],x.get('tencent',''),source=source),index_quality)
            rows.append(row)
            previous=mk['index'].get(x['symbol'])
            if value and build.latest.select_index(value,None,snapshot_clock if snapshot_clock is not None else dt.datetime.now(build.BJ)) and (not previous or value.get('date','')>previous.get('date','')):
                mk['index'][x['symbol']] = value
    for cur in currencies:
        row,value=inspect('fx',cur,'yahoo',budget,lambda h:quotes.fx(h,cur),lambda v,h:fx_quality(v,h,cur))
        rows.append(row)
        if value: mk['fx'][cur]=value
    cfg=data['config']['ratio']
    for key, prefix in (('cyb','growth'),('hl','dividend')):
        for source in ('tencent','yahoo'):
            row,value=inspect('ratio-'+source,key,source,budget,
                lambda h:quotes.monthly(h,cfg[prefix+'_tencent'],cfg[prefix+'_yahoo']),month_quality)
            rows.append(row)
            if source=='tencent' and value: mk['ratio'][key]=value
    # Freeze once AFTER the last source result: receivedAt must not be in the
    # future relative to this clock. Transport event times remain actual times.
    fixed_clock = snapshot_clock if snapshot_clock is not None else dt.datetime.now(build.BJ)
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


def preflight():
    data,report=build.load_and_validate(build.RADAR,ROOT,dt.datetime.now(build.BJ).date())
    if report.errors: raise StopProbe('schema_errors')
    proc=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','radar/tests','-v'],cwd=ROOT,capture_output=True)
    output=(proc.stdout+proc.stderr).decode('utf-8','replace')
    match=re.search(r'Ran (\d+) tests?',output)
    count=int(match[1]) if match else 0
    if proc.returncode or count<55: raise StopProbe('offline_tests_failed')
    return {'tests':count,'schemaWarnings':len(report.warnings),'schemaErrors':len(report.errors)}


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
    data,rep=build.load_and_validate(build.RADAR,ROOT,dt.datetime.now(build.BJ).date())
    if rep.errors: raise StopProbe('schema_errors')
    receipt={'schemaVersion':1,'purpose':'interface-acceptance-not-publication','startedAt':utc(),
             'execution':{k:os.environ.get(k) for k in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','RUNNER_OS','RUNNER_ARCH','ImageOS','ImageVersion')},
             'python':platform.python_version(),'kernel':platform.release(),
             'limits':{'requests':MAX_REQUESTS,'timeoutSeconds':TIMEOUT,'deadlineSeconds':DEADLINE,'attemptsPerGet':2,'retryOnly429':True,'maxRetryAfterSeconds':10},
             'schemaWarnings':len(rep.warnings),'fallbackPolicy':'separate-source-only; query2 not attempted; access denials stop corresponding lane'}
    budget=Budget()
    snapshot = {}
    rows,summary,session,gates=collect(data,budget,snapshot_sink=snapshot)
    receipt.update(results=rows,summary=summary,quoteSession=session,publication=gates,
                   requestsMade=budget.count,deniedPaths=sorted(budget.denied),finishedAt=utc(),
                   fixedClock=snapshot['clock'].isoformat())
    saved = bundle.write_bundle(args.out.parent, snapshot['data'], receipt, snapshot['clock'])
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
