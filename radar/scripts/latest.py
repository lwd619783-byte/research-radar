"""Independent latest quotes and per-market completed daily metrics. No fetching."""
import datetime as dt
from zoneinfo import ZoneInfo
from integrity import ZONES, fresh_record, number, observation_time, dated_fx
from snapshot import completed_bars, CLOSED_QUOTE_STATES


def select_daily(companies, records, now):
    selected, sources, dates = {}, {}, {}
    for c in companies:
        r = records.get(c['sym']) or {}
        if r.get('asOf'): sources.setdefault(c['mkt'], set()).add(r['asOf'])
        bars = completed_bars(r)
        if r.get('currency') not in (None, c['cur']): bars = []
        if r.get('timezone'):
            try:
                if any(dt.datetime.fromisoformat(b[0]).replace(tzinfo=ZoneInfo(r['timezone'])).utcoffset() != dt.datetime.fromisoformat(b[0]).replace(tzinfo=ZoneInfo(ZONES[c['mkt']])).utcoffset() for b in bars): bars=[]
            except (ValueError, TypeError, KeyError): bars=[]
        local = now.astimezone(ZoneInfo(ZONES[c['mkt']])).date()
        if bars and 0 <= (local-dt.date.fromisoformat(bars[-1][0])).days <= 4:
            day=bars[-1][0]
            selected[c['sym']]={**r,'bars':bars,'asOf':day,'phase':'closed',
                'snapshotSelection':{'method':'latest-completed-per-market','selectedDate':day,'sourceAsOf':r.get('asOf'),'sourcePhase':r.get('phase')}}
            dates.setdefault(c['mkt'],set()).add(day)
    all_dates=sorted({d for ds in dates.values() for d in ds})
    return selected, {'policy':'latest-quote-and-market-completed-daily','selectedDate':max(all_dates) if all_dates else None,
        'dateRange':all_dates,'status':'complete' if len(selected)==len(companies) else 'incomplete',
        'selectedCompanies':len(selected),'requiredCompanies':len(companies),
        'sourceAsOfByMarket':{k:sorted(v) for k,v in sources.items()},'metricAsOfByMarket':{k:sorted(v) for k,v in dates.items()}}


def quote_phase(record):
    state=record.get('marketState')
    return 'intraday' if state=='REGULAR' else 'closed' if state in CLOSED_QUOTE_STATES else 'unknown'


def select_quote(record, day, market, currency, now):
    observed=observation_time('quote',record)
    local=observed.astimezone(ZoneInfo(ZONES[market])).date().isoformat() if observed else None
    if not local:return {},'quote_date_mismatch_or_missing',None
    if not fresh_record(record,now,local,market):return {},'quote_stale_or_invalid_receipt',local
    if observed>dt.datetime.fromisoformat(record['receivedAt']):return {},'quote_observation_after_receipt',local
    if record.get('currency')!=currency:return {},'quote_currency_mismatch',local
    return record,'available',local


def select_fx(record, currency, quote_day, now):
    if not isinstance(record,dict):return None
    exact=dated_fx(record,currency,quote_day,now) if quote_day else None
    if exact:return {**exact,'estimated':False,'valuationDate':quote_day,'maxDateGapDays':4}
    # Explicit estimate only: a proven completed FX close, <=4 calendar days old
    # and <=4 days from the valuation. Receipt age remains <=36h. No future rates.
    day=record.get('asOf')
    if not day or not quote_day:return None
    try:
        gap=(dt.date.fromisoformat(quote_day)-dt.date.fromisoformat(day)).days
        if not 0<=gap<=4:return None
    except ValueError:return None
    result=dated_fx(record,currency,day,now)
    return {**result,'estimated':True,'valuationDate':quote_day,'dateGapDays':gap,'maxDateGapDays':4} if result else None


def select_index(record, day, now):
    if not isinstance(record,dict) or not record.get('date'):return None
    # Current index level is independently dated; unknown phase is explicit,
    # not silently upgraded. Valid dates/prices and source receipt still required.
    if not fresh_record(record,now,record['date']):return None
    if not record.get('src') or not number(record.get('price')) or record['price']<=0 or not number(record.get('chg')):return None
    return record


def comparable_ratio(rc,rh,now):
    if not isinstance(rc,dict) or not isinstance(rh,dict):return None
    tc,th=observation_time('ratio',rc),observation_time('ratio',rh)
    if tc is None or th is None:return None
    # Preserve the original current-observation contract before aligning two
    # independently dated daily series. Never infer dates from monthly buckets.
    def observations(r):
        result={r['current']['date']:r['current']['close']}
        previous=''
        for x in r.get('dailyObservations',[]):
            try:
                if (not isinstance(x,list) or len(x)!=2 or not isinstance(x[0],str)
                        or dt.date.fromisoformat(x[0]).isoformat()!=x[0]
                        or x[0]<=previous or x[0]>r['asOf']
                        or not number(x[1]) or x[1]<=0
                        or (x[0] in result and result[x[0]]!=x[1])):
                    return None
            except (ValueError,TypeError):
                return None
            previous=x[0];result[x[0]]=x[1]
        return result
    a,b=observations(rc),observations(rh)
    if a is None or b is None:return None
    common=sorted(set(a)&set(b))
    if not common:return None
    day=common[-1]
    if not fresh_record(rc,now,day) or not fresh_record(rh,now,day):return None
    left=[[m,v] for m,v in rc['bars'] if m<day[:7]]+[[day[:7],a[day]]]
    right=[[m,v] for m,v in rh['bars'] if m<day[:7]]+[[day[:7],b[day]]]
    return day,left,right


def coverage_matrix(D):
    rows=[]
    for c in D['companies']:
        p=c['provenance'];v=p['valuation'];f=p['financial']
        for metric,value in [('price',c['price']),('daily',c['ld']),('r5',c['r5']),('r20',c['r20']),('r60',c['r60']),('ytd',c['ytd']),('high52',c.get('hi52')),('marketCap',c.get('mcapLocal')),('marketCapUSD',c['mcapUSD']),('PE',c['pe'])]:
            status='complete' if value is not None else 'missing'
            reason='available' if value is not None else ('source_missing' if metric=='PE' else 'missing_or_incompatible')
            if metric=='PE':
                reason=v.get('peStatus','missing')
                if reason=='not_meaningful':status='not_applicable'
            if metric in ('price','marketCap','marketCapUSD','PE') and value is not None and (c.get('pricePhase') if metric=='price' else v.get('phase'))=='unknown':status='partial';reason='quote_phase_unknown'
            if metric=='marketCapUSD' and value is not None and (v.get('fx') or {}).get('estimated'):status='partial';reason='dated_fx_estimate'
            if c.get('stale') and value is not None and (metric in ('daily','r5','r20','r60','ytd','high52') or (metric=='price' and not c.get('priceObservedAt'))):status='partial';reason='cached_or_stale_daily'
            rows.append({'kind':'company','symbol':c['sym'],'metric':metric,'status':status,'reason':reason,'date':c.get('priceAsOf') if metric=='price' else c['ld'] if metric in ('daily','r5','r20','r60','ytd','high52') else v.get('asOf'),'evidence':{'epsTrailingTwelveMonths':v.get('epsTrailingTwelveMonths')} if metric=='PE' else None,'source':c.get('priceSource') if metric=='price' else p['daily'].get('src') if metric in ('daily','r5','r20','r60','ytd','high52') else v.get('source')})
        rows.append({'kind':'company','symbol':c['sym'],'metric':'financial','status':'complete' if f['status']=='verified' else 'partial' if c['financialPartial'] else 'missing','reason':f['status'],'date':f.get('period_end'),'source':f.get('source_name')})
    for symbol in D['meta']['configuredIndices']:
        v=next((x for x in D['indices'] if x['symbol']==symbol),None)
        rows.append({'kind':'index','symbol':symbol,'status':'missing' if not v else 'partial' if v.get('phase')=='unknown' else 'complete','date':v.get('asOf') if v else None,'source':v.get('source') if v else None,'reason':'missing' if not v else 'phase_unknown' if v.get('phase')=='unknown' else 'available'})
    for currency in D['meta']['requiredFX']:
        v=D['meta']['fxProvenance'].get(currency)
        rows.append({'kind':'fx','symbol':currency,'status':'complete' if v else 'missing','date':v.get('asOf') if v else None,'source':v.get('src') if v else None})
    rows.append({'kind':'ratio','symbol':'growth/dividend','status':'partial' if D['ratio'] else 'missing','reason':'common_daily_date_not_proven_simultaneous' if D['ratio'] else 'insufficient_comparable_observations','date':D['ratio'].get('asOf') if D['ratio'] else None})
    return rows
