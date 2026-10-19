"""OFFLINE mixed-date replay; no requests, not a new complete market snapshot.
Run from repository root. Output archive remains in /tmp, only summary is saved.
"""
import collections,copy,datetime as dt,gzip,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'radar/scripts'))
import build,quotes,acceptance_bundle as bundle
HERE=Path(__file__).resolve().parent
captured=json.loads((HERE/'valuation-fx-evidence.json').read_text())
targeted=json.loads((HERE/'targeted-source-evidence.json').read_text())
clock=dt.datetime.fromisoformat(captured['finishedAt']).astimezone(build.BJ)
data,report=build.load_and_validate(build.RADAR,ROOT,clock.date());assert not report.errors
mk=json.loads(gzip.decompress((ROOT/'audit/truthfulness-2026-10-18/fixtures/market-finality.json.gz').read_bytes()))
mk['quote']=captured['quote'];mk['fx']=captured['fx']
for x in data['config']['indices']:
 code=x.get('tencent');v=targeted['tencent'].get(code)
 if not v:continue
 qt=['']*v['qtLength']
 for k,value in v['quoteFields'].items():qt[int(k)]=value
 node={'day':v['rows'],'qt':{code:qt}}
 class SavedHTTP:
  def json(self,url):return {'data':{code:node}}
 r=quotes.index_quote(SavedHTTP(),x['symbol'],code,source='tencent')
 # Restore exact source receipt; adapter call is offline and must not refresh it.
 r['receivedAt']=v['receivedAt']
 old=mk['index'].get(x['symbol'])
 if not old or r['date']>old['date']:mk['index'][x['symbol']]=r
fresh={**mk,'daily':{},'offline':True}
D,stale,missing=build.assemble(data,mk,fresh,clock)
D['meta'].update(reviewPreview=True,fixture='OFFLINE MIXED-DATE REPLAY: saved 2026-10-18 daily/ratio + 2026-10-19 targeted quotes/FX/indices; not an after-close full run')
receipt={'schemaVersion':1,'purpose':D['meta']['fixture'],'fixedClock':clock.isoformat(),
 'execution':{'GITHUB_SHA':'3483e537d8ffc8d9a3f59f3294ba6b2e59a5fceb','GITHUB_RUN_ID':'0','GITHUB_RUN_ATTEMPT':'1'},
 'requestsMade':0,'publication':{'asOf':D['meta']['asOf'],'snapshot':D['meta']['snapshot'],
 'dataSHA256':bundle.data_digest(D),'blockers':build.release_blockers(D),'coverage':D['meta']['coverage']}}
with tempfile.TemporaryDirectory(prefix='radar-mixed-replay-') as tmp:
 out=Path(tmp)/'archive';saved=bundle.write_bundle(out,D,receipt,clock)
 assert bundle.verify_bundle(out)==saved
 # Only the exact HTML needed for screenshots is retained locally, outside Git.
 Path('/tmp/radar-latest-replay.html').write_bytes((out/'index.html').read_bytes())
summary={'classification':D['meta']['fixture'],'fixedClock':clock.isoformat(),'requestsMade':0,
 'sourceReceiptsPreserved':True,'staleDaily':len(stale),'missingDaily':len(missing),
 'priceDateRange':D['meta']['priceDateRange'],'metricsAsOfByMarket':D['meta']['asOfByMarket'],
 'coverageComplete':D['meta']['coverageComplete'],'coverageStatusCounts':dict(collections.Counter(r['status'] for r in D['meta']['coverage'])),
 'counts':{'companies':len(D['companies']),'price':sum(c['price'] is not None for c in D['companies']),
 'marketCapLocal':sum(c['mcapLocal'] is not None for c in D['companies']),
 'marketCapUSD':sum(c['mcapUSD'] is not None for c in D['companies']),
 'marketCapEstimated':sum(c['mcapEstimated'] for c in D['companies']),
 'PE':sum(c['pe'] is not None for c in D['companies']),'indices':len(D['indices']),
 'FX':len(D['meta']['fxProvenance']),'ratio':bool(D['ratio'])},
 'blockers':build.release_blockers(D),'archiveRoundTrip':saved,
 'selectedCompanyEvidence':[{k:c.get(k) for k in ('sym','price','priceAsOf','priceObservedAt','pricePhase','metricAsOf','mcapLocal','mcapUSD','mcapEstimated','history','pe')} for c in D['companies'] if c['sym'] in ('688825.SS','688498.SS','LITE','000660.KS')],
 'ratioEvidence':{k:D['ratio'].get(k) for k in ('asOf','completedMonths','simultaneousObservationProven')} if D['ratio'] else None}
(HERE/'replay-summary.json').write_bytes(bundle.encoded(summary))
(HERE/'coverage-matrix.json').write_bytes(bundle.encoded({'classification':D['meta']['fixture'],'rows':D['meta']['coverage']}))
print(json.dumps({k:v for k,v in summary.items() if k not in ('selectedCompanyEvidence','archiveRoundTrip')},ensure_ascii=False))
