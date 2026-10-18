"""Read six public FX histories with the bounded probe transport, never publish."""
import ast
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'radar/scripts'))
import acceptance_probe as probe
import quotes
FIX=HERE/'fixtures';FIX.mkdir(exist_ok=True)
# Prefer the committed original evidence; /tmp was only the first capture input.
original=FIX/'market-original.json.gz'
raw_market=gzip.decompress(original.read_bytes()) if original.exists() else Path('/tmp/radar-live-market.json').read_bytes()
assert hashlib.sha256(raw_market).hexdigest()=='7104fc3546ed56aa9878e98c8c0632da0b776948fd4f12b6ac9af488555006d2'
market=json.loads(raw_market)
# Known public normalized fields only; no source headers, cookies, crumb or account data.
allowed={
 'daily':{'asOf','bars','currency','phase','priceBasis','receivedAt','returnBasis','schemaVersion','src'},
 'quote':{'currency','marketCap','receivedAt','regularMarketTime','schemaVersion','src','trailingPE'},
 'index':{'chg','date','phase','price','receivedAt','schemaVersion','sourceDiagnostics','src'},
 'fx':{'asOf','currency','direction','priceBasis','rates','receivedAt','schemaVersion','src','timezone','value'},
 'ratio':{'asOf','bars','current','periodDates','receivedAt','schemaVersion','src'}}
assert set(market)==set(allowed)
for kind,records in market.items():
    for record in records.values():assert set(record)<=allowed[kind],(kind,set(record)-allowed[kind])
(FIX/'market-original.json.gz').write_bytes(gzip.compress(raw_market,mtime=0))
budget=probe.Budget();rows=[];raw_responses={};new_fx={}
start=probe.utc()
for cur in sorted(market['fx']):
    h=probe.ProbeHttp(budget,'yahoo')
    try:
        value=quotes.fx(h,cur)
        r=h.documents[-1]['chart']['result'][0]
        safe={'chart':{'result':[{'meta':{k:r['meta'][k] for k in ('exchangeTimezoneName','regularMarketTime','regularMarketPrice','currentTradingPeriod','dataGranularity') if k in r['meta']},'timestamp':r['timestamp'],'indicators':{'quote':[{'close':r['indicators']['quote'][0]['close']}]}}]}}
        raw_responses[cur]=safe;new_fx[cur]=value
        fields,details,gate=probe.fx_quality(value,h,cur)
        rows.append(dict(currency=cur,requests=h.events,checks=fields,details=details,quality=all(fields.values()),gate=gate))
    except Exception as e:
        rows.append(dict(currency=cur,requests=h.events,failure=type(e).__name__))
        if budget.denied:break
# Persist successful records only; failure never manufactures historical proof.
market['fx']=new_fx
payload=json.dumps(market,ensure_ascii=False,separators=(',',':')).encode()
(FIX/'market-finality.json.gz').write_bytes(gzip.compress(payload,mtime=0))
(FIX/'fx-public-responses.json').write_text(json.dumps(raw_responses,ensure_ascii=False,indent=2)+'\n')
# Actual legacy producer applied to one recorded public response. This is a
# reproducible reconstruction, not a claimed surviving production cache file.
base='414eb80626d3200dfebe4a010507c5fe74d7ca31'
legacy_source=subprocess.check_output(['git','show',base+':radar/scripts/quotes.py'],cwd=ROOT,text=True)
node=next(n for n in ast.parse(legacy_source).body if isinstance(n,ast.FunctionDef) and n.name=='fx')
namespace=dict(vars(quotes));exec(compile(ast.Module(body=[node],type_ignores=[]),'<legacy-fx>','exec'),namespace)
class RecordedHttp:
    def yahoo(self,path):return raw_responses['CNY']
legacy=namespace['fx'](RecordedHttp(),'CNY')
(FIX/'legacy-fx-cache.json').write_text(json.dumps({'fx':{'CNY':legacy}},indent=2)+'\n')
manifest=dict(startedAt=start,finishedAt=probe.utc(),replayAt=probe.utc(),legacyProducerSHA=base,
 originalSnapshotSHA256=hashlib.sha256(raw_market).hexdigest(),newRequests=budget.count,results=rows,
 legacyFixture='Unmodified baseline fx() executed against recorded public CNY response; not an original saved production cache. Synthetic closed-equity responses used only inside fallback tests.',
 snapshotPublicFieldsReviewed=allowed and True,
 files={f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),**({'uncompressedSHA256':hashlib.sha256(gzip.decompress(f.read_bytes())).hexdigest()} if f.suffix=='.gz' else {})} for f in FIX.iterdir()})
(HERE/'fx-finality-capture.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'requests':budget.count,'currencies':list(new_fx),'quality':[r.get('quality') for r in rows],'legacyAsOf':legacy['asOf'],'legacyKeys':list(legacy)},indent=2))
