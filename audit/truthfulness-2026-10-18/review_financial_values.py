"""Replay reviewed arithmetic against downloaded public texts; never auto-write TOML."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import math
import re
HERE=Path(__file__).resolve().parent
RAW=Path('/tmp/radar-public-financial-sources')
pack=json.loads((HERE/'financial-candidates-received.json').read_text())
candidates={c['id']:c for c in pack['candidates']}
# Manually read consolidated statement lines: current/previous revenue, parent
# profit, and current reported gross profit. Values use each statement's unit.
direct={
'LITE':[1006.3,480.7,-7161.7,213.3,477.3],
'AVGO':[29591,15952,13088,4140,20456],
'MRVL':[2739.3,2006.1,308.,194.8,1455.6],
'ANET':[3035.7,2204.8,1212.9,888.8,1910.3],
'TSM':[1494243,989918,763064,452302,992379],
'ASMPT':[4935800,3244331,335136,131214,2092487],
'SKH':[79318746,22231952,93820236,6997228,65991356],
'MU':[54229,11315,37701,3201,47047],
'NVDA':[96221,46743,59688,26422,72142],
'ASML':[11662.,7516.,4960.4,2124.5,6699.8],
'NTB':[34033,28231,5797,3147,14914],
'EMC':[47275194,22507694,9873398,3477879,16002991],
'GEV':[11104,9111,668,514,2360],
'ENR':[11447,9745,1083,615,2669],
'ETN':[8531,7028,821,982,8531-5676],
'VRT':[3274.3,2638.1,497.8,324.2,3274.3-2039.4],
'MOD':[874.1,682.8,73.9,51.2,182.],
}
manual_cn={
 'HDGF': {'h1':{'revenue':[13689427504,8493871883], 'cost':[8389487706,5508789969], 'profit':[2923361746,1682780947]},
          'q1':{'revenue':[6214156406,4037627327], 'cost':[3999902225,2715105615], 'profit':[1242081367,762465400]}},
 'CXMT': {'h1':{'revenue':[150310076758.,15437924611.51], 'cost':[22934480656.80,13430877836.86], 'profit':[77605227520.,-2332058185.65]},
          'q1':{'revenue':[50800145545.85,6201690535.94], 'cost':[10587996319.55,5386882851.70], 'profit':[24762031466.04,-1559027880.10]}}
}

def text_for(cid,index=0):
    u=candidates[cid]['source_urls'][index]
    return (RAW/(hashlib.sha256(u.encode()).hexdigest()[:16]+'.txt')).read_text()

def appears(number,text):
    # Exact monetary string, not semantic proof; statement/column roles above
    # were reviewed separately. Accommodate thousands separators and spaces.
    text=re.sub(r'[,\s]','',text)
    return format(abs(number),'.2f').rstrip('0').rstrip('.') in text

def computed(v):
    rev,prior,profit,priorprofit,gross=v
    return dict(revenue_yoy=(rev/prior-1)*100,
                profit_yoy=(profit/priorprofit-1)*100 if priorprofit>0 else None,
                gross_margin=gross/rev*100)

rows={r['id']:r for r in json.loads((HERE/'cn-quarter-recalculation.json').read_text()) if r.get('computed')}
for cid,input in manual_cn.items():
    for i,k in enumerate(('h1','q1')):
        text=text_for(cid,i)
        for pair in input[k].values():
            for v in pair: assert appears(v,text),(cid,v)
    q={k:[input['h1'][k][i]-input['q1'][k][i] for i in (0,1)] for k in ('revenue','cost','profit')}
    rows[cid]=dict(id=cid,inputs=input,quarter=q,computed=computed([*q['revenue'],*q['profit'],q['revenue'][0]-q['cost'][0]]))
for cid,values in direct.items():
    text=text_for(cid)
    raw_values=values if cid not in ('ETN','VRT') else values[:4]+([5676] if cid=='ETN' else [2039.4])
    for v in raw_values: assert appears(v,text),(cid,v)
    rows[cid]=dict(id=cid,statementInputs=values,computed=computed(values))
rows['ASML']['rawCalculatedGrossMargin']=rows['ASML']['computed']['gross_margin']
assert '57.5' in text_for('ASML')
rows['ASML']['computed']['gross_margin']=57.5
rows['ASML']['review']='Use explicitly reported US GAAP margin 57.5%; displayed 6699.8/11662=57.449837%, crossing one-decimal rounding boundary. Preserve discrepancy.'
# Explicit issuer-reported percentages / exceptions, not arithmetic inference.
assert all(x in text_for('COHR') for x in ('33.8','38.5','(96','241'))
rows['COHR']=dict(id='COHR',computed=dict(revenue_yoy=33.8,profit_yoy=None,gross_margin=38.5),
                 review='Use issuer reported revenue +33.8%; displayed decimals recompute +33.7453%, rounding discrepancy retained. Prior parent loss; no growth percentage.',
                 displayedParentEarnings=[241,-96])
assert all(x in text_for('SU') for x in ('17.9','16.9','11,460','October 16'))
rows['SU']=dict(id='SU',computed=dict(revenue_yoy=17.9,profit_yoy=None,gross_margin=None),
               review='Revenue-only Q3; reported +17.9%, not organic +16.9%. No H1 profit or margin carried into Q3.')
assert len(rows)==40
for cid,row in rows.items():
    cand=candidates[cid]['fin_schema_compatible_candidate']
    row['candidate']= {k:cand[k] for k in ('revenue_yoy','profit_yoy','gross_margin')}
    row['deltas']={k:None if value is None else value-cand[k] for k,value in row['computed'].items()}
    for k,value in row['computed'].items():
        if value is None: assert cand[k] is None,(cid,k)
        else:
            decimals=len(str(cand[k]).split('.')[1]) if '.' in str(cand[k]) else 0
            assert abs(value-cand[k])<=.5*10**(-decimals)+1e-6,(cid,k,value,cand[k])
    row['conditionsReviewed']=True
    row['source_urls']=candidates[cid]['source_urls']
    row['checkedAt']=dt.datetime.now(dt.UTC).isoformat()
    row['candidateVerifiedAtUnchanged']=cand['verified_at']
    row['status']='arithmetic_and_scope_checked; publication_date_provenance_retained_from_candidate'
(HERE/'financial-content-review.json').write_text(json.dumps(list(rows.values()),ensure_ascii=False,indent=2)+'\n')
print('40 unique candidates: arithmetic/issuer-reported values checked; nulls preserved; original verified_at retained')
