"""Reproduce synthetic snapshot outcomes offline; writes only JSON to stdout."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'radar/tests'))
from test_completed_snapshot import MONDAY, monday_dataset
from test_integrity import build, historical_fx
from integrity import release_blockers


def summarize(data,mk):
    D,stale,missing=build.assemble(data,mk,mk,MONDAY)
    rows={c['sym']:c for c in D['companies']}
    return {'snapshot':D['meta']['snapshot'],'asOfByMarket':D['meta']['asOfByMarket'],
        'blockers':release_blockers(D),'missingDailyCount':len(missing),'staleDailyCount':len(stale),
        'marketCapAvailable':sum(c['mcapUSD'] is not None for c in rows.values()),
        'peAvailable':sum(c['pe'] is not None for c in rows.values()),
        'financialVerified':sum(c['provenance']['financial']['status']=='verified' for c in rows.values()),
        'financialPartial':sum(c['financialPartial'] for c in rows.values()),
        'partialScored':sum(c['financialSignalEligible'] for c in rows.values() if c['financialPartial']),
        'indicesAvailable':len(D['indices']),'fxDates':{k:v['asOf'] for k,v in D['meta']['fxProvenance'].items()},
        'selectedRows':{sym:{'date':rows[sym]['ld'],'price':rows[sym]['price'],
            'pe':rows[sym]['pe'],'marketCapUSD':rows[sym]['mcapUSD'],
            'history':rows[sym]['history'],'valuation':rows[sym]['provenance']['valuation']}
            for sym in ('000660.KS','3110.T','2383.TW','LITE','688825.SS')},
        'issues':D['meta']['issues']}


def main():
    _,mk=monday_dataset()
    # Use unchanged reviewed financial inputs; all market scenarios remain
    # explicitly synthetic, including altered collection/observation timestamps.
    data,report=build.load_and_validate(build.RADAR,ROOT,MONDAY.date())
    assert not report.errors
    output={'kind':'synthetic offline scenarios, NOT an Actions receipt or live replay',
            'fixedClock':MONDAY.isoformat(),'networkRequests':0,'scenarios':{}}
    output['scenarios']['monday_mixed_markets']=summarize(data,mk)
    fx_missing=copy.deepcopy(mk)
    fx_missing['fx']['CNY']=historical_fx('CNY',rates=[['2026-10-15',7.,7.]],receivedAt=MONDAY.isoformat())
    output['scenarios']['no_exact_day_cny_fx']=summarize(data,fx_missing)
    unknown=copy.deepcopy(mk)
    unknown['index'][data['config']['indices'][0]['symbol']]['phase']='unknown'
    output['scenarios']['unknown_index_still_blocks']=summarize(data,unknown)
    legacy=copy.deepcopy(mk)
    for q in legacy['quote'].values():q.pop('marketState',None)
    output['scenarios']['legacy_quotes_not_promoted']=summarize(data,legacy)
    print(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
