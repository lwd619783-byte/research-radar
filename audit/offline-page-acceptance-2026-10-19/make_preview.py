"""Offline component fixture only. Never fetch market data or claim a run replay."""
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'radar/tests'))
from test_completed_snapshot import session_record, epoch
from test_integrity import build, historical_fx
from test_review_regressions import monthly_record
from integrity import ZONES, release_blockers

NOW=dt.datetime(2026,10,19,2,38,tzinfo=dt.UTC);DAY='2026-10-16'
RETAIN={'LITE','COHR','AVGO','MRVL','ANET','TSM','0522.HK','MU','NVDA','ASML','1888.HK','GEV','ENR.DE','ETN','SU.PA','VRT','MOD'}
MISSING_INDICES={'399006.SZ','000922.SS','HSTECH.HK'}

def main():
 data,report=build.load_and_validate(build.RADAR,ROOT,NOW.date());assert not report.errors
 mk={k:{} for k in ('daily','quote','fx','index','ratio')}
 start=dt.date(2023,1,2);end=dt.date.fromisoformat(DAY)
 days=[(start+dt.timedelta(days=i)).isoformat() for i in range((end-start).days+1) if (start+dt.timedelta(days=i)).weekday()<5]
 fixture=ROOT/'audit/truthfulness-2026-10-18/fixtures/market-finality.json.gz'
 old=json.loads(gzip.decompress(fixture.read_bytes()))
 for i,c in enumerate(data['companies']):
  retained=c['sym'] in RETAIN
  bars=[[day,round(40+i*3+j*.018+math.sin(j*.18+i)*1.8,3),round(40+i*3+j*.018+math.sin(j*.18+i)*1.8,3),round(44+i*3+j*.018+math.sin(j*.18+i)*1.8,3)] for j,day in enumerate(days)]
  if c['sym']=='688825.SS':bars=old['daily'][c['sym']]['bars']
  if not retained:bars=bars+[['2026-10-19',999.,999.,1000.]]
  r=session_record([b[0] for b in bars],c['mkt'],now=NOW,currency=c['cur']);r['bars']=bars
  mk['daily'][c['sym']]=r
  mk['quote'][c['sym']]={'schemaVersion':2,'receivedAt':NOW.isoformat(),'src':'synthetic-test-only','currency':c['cur'],
    'marketCap':(100+i*31)*1e8,'trailingPE':None if c['sym']=='LITE' else 10+i*.7,
    'regularMarketTime':epoch(DAY,ZONES[c['mkt']],16) if retained else (NOW-dt.timedelta(minutes=1)).timestamp(),
    'marketState':'CLOSED' if retained else 'REGULAR'}
  if c['cur']!='USD':mk['fx'][c['cur']]=historical_fx(c['cur'],receivedAt=NOW.isoformat())
 for i,x in enumerate(data['config']['indices']):
  if x['symbol'] not in MISSING_INDICES:
   mk['index'][x['symbol']]={'schemaVersion':2,'receivedAt':NOW.isoformat(),'src':'synthetic-test-only','phase':'closed','date':DAY,'price':3000+i*173,'chg':.005+i*.001}
 mk['ratio']={'cyb':monthly_record('2026-10-19'),'hl':monthly_record('2026-10-19',True)}
 for r in mk['ratio'].values():r['receivedAt']=NOW.isoformat()
 D,stale,missing=build.assemble(data,mk,mk,NOW)
 assert not stale and not missing and D['meta']['asOf']==DAY
 assert sum(c['mcapUSD'] is not None for c in D['companies'])==17
 assert sum(c['pe'] is not None for c in D['companies'])==16
 assert D['ratio'] is None and len(D['indices'])==5
 assert next(c for c in D['companies'] if c['sym']=='688825.SS')['history']['count']==54
 D['meta'].update(fixture='SYNTHETIC COMPONENT TEST: prices/valuations fabricated; prior CXMT sample only; NOT run 39190870708 page',reviewPreview=True,offline=True)
 D['meta']['blockers']=release_blockers(D)
 (HERE/'test-data.json').write_text(json.dumps(D,ensure_ascii=False,indent=2)+'\n')
 with tempfile.TemporaryDirectory() as td:html=build.render(D,Path(td)).read_text()
 html=html.replace('<head>','<head>\n<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; font-src data:; connect-src \'none\'; base-uri \'none\'; form-action \'none\'">',1)
 html=html.replace('<title>','<title>【离线测试数据·非真实运行页面】',1)
 notice='<aside id="audit-fixture-notice" style="position:fixed;bottom:0;left:0;right:0;z-index:2147483647;padding:12px 18px;background:#ffdb73;color:#211800;font:700 16px/1.4 sans-serif;text-align:center;box-shadow:0 -2px 12px #0008">离线组件验收 · 测试数据（合成行情＋旧样本） · 非本次 Actions 真实页面 · 未发布</aside>'
 html=html.replace('</body>',notice+'\n</body>')
 (HERE/'preview.html').write_text(html)
 evidence={'generatedAt':dt.datetime.now(dt.UTC).isoformat(),'fixtureClock':NOW.isoformat(),'dataType':'Explicit synthetic component fixture, not reconstructed Actions data','marketRequests':0,'externalDeployment':False,
 'patternSource':'Parent independently verified run 39190870708 receipt summary only; used to choose missingness pattern, never to reconstruct actual prices.',
 'priorCXMTSource':{'path':str(fixture.relative_to(ROOT)),'sha256':hashlib.sha256(fixture.read_bytes()).hexdigest(),'selectedFixtureCount':54,'warning':'54 is this older local sample count, not a directly observed selected-bar count in run 39190870708 receipt'},
 'financeSource':'Unchanged repository public evidence: 40 verified / 2 partial',
 'syntheticFields':['all other daily prices/returns','all market capitalization and PE values','all index values','all FX numeric rates','session and receipt timestamps'],
 'fixtureCounts':{'companies':42,'marketCap':17,'PE':16,'missingMarketCap':25,'missingPE':26,'indices':5,'ratioAvailable':False},
 'realPreviewMissing':['run 39190870708 complete selected company bar arrays and metrics','actual selected valuation numeric fields','assembled index list and values','assembled FX numeric values/provenance','full assembled DATA'],
 'localInspected':{'radar/.cache':'absent','radar/dist':'absent','audit/runtime/build-report.json':'2026-10-18 generated; asOf null; unsuitable','priorMarketFixture':'2026-10-18, no marketState in quote records; not current run'},
 'previewOnlyAdditions':['CSP disables network','fixed explicit test-data watermark','test-data title'],
 'productionFrontendFilesChanged':False,'releaseBlockers':D['meta']['blockers'],
 'outputs':{name:{'bytes':(HERE/name).stat().st_size,'sha256':hashlib.sha256((HERE/name).read_bytes()).hexdigest()} for name in ('preview.html','test-data.json')}}
 (HERE/'data-provenance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(evidence['fixtureCounts'],ensure_ascii=False))
if __name__=='__main__':main()
