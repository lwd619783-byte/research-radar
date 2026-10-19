"""Offline only. Requires the ORIGINAL verified run 39214475581 four-file bundle.
No substitute fixture, download, Actions dispatch, or market API is implemented.
Writes a new review HTML separately; never changes the four input files.
"""
import argparse,collections,datetime as dt,hashlib,json,sys,threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'radar/scripts'))
import build,acceptance_bundle as bundle

def sha(blob):return hashlib.sha256(blob).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
 required=set(bundle.FILES)
 missing=[name for name in required if not (args.bundle/name).is_file()]
 if missing:raise SystemExit('Original verified bundle unavailable: '+', '.join(sorted(missing)))
 assert {p.name for p in args.bundle.iterdir()}==required
 raw={name:(args.bundle/name).read_bytes() for name in required}
 D=json.loads(raw['DATA.json']);receipt=json.loads(raw['receipt.json']);manifest=json.loads(raw['manifest.json'])
 assert receipt['execution']['GITHUB_RUN_ID']=='39214475581'
 assert receipt['execution']['GITHUB_SHA']=='b629883c76f578be4dac2740e5bfc5e8bfa4cb35'
 assert receipt['execution']['GITHUB_RUN_ATTEMPT']=='1'
 assert not any(D['meta'].get(k) for k in ('fixture','offline','reviewPreview'))
 assert sum(map(len,raw.values()))==manifest['totalBytes']<=10_000_000
 for name in bundle.PAYLOADS:assert manifest['files'][name]=={'bytes':len(raw[name]),'sha256':sha(raw[name])}
 assert bundle.embedded_data(raw['index.html'])==D
 bundle.validate_binding(D,receipt,dt.datetime.fromisoformat(receipt['fixedClock']))
 counts=dict(collections.Counter(r['status'] for r in D['meta']['coverage']))
 assert counts=={'complete':441,'partial':31,'not_applicable':1,'missing':4}
 assert len(D['companies'])==42 and len(D['indices'])==8 and len(D['meta']['coverage'])==477
 assert next(c for c in D['companies'] if c['sym']=='688825.SS')['history']['count']==55
 args.out.mkdir(parents=True,exist_ok=True)
 original=bundle.encoded(D)
 pagefile=build.render(D,args.out)
 html=pagefile.read_text().replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; font-src data:; connect-src \'none\'; base-uri \'none\'; form-action \'none\'">',1)
 html=html.replace('</body>','<aside style="position:fixed;bottom:0;left:0;right:0;z-index:2147483647;padding:8px;background:#ffdb73;color:#211800;font:700 12px sans-serif;text-align:center">交互验收 · 未发布 · 数据保留 run 39214475581 原时点；此页为新版界面，非 Actions 原始 HTML</aside></body>')
 pagefile.write_text(html)
 assert bundle.embedded_data(html.encode())==D and bundle.encoded(D)==original
 assert all((args.bundle/n).read_bytes()==raw[n] for n in raw)
 report={'startedAt':dt.datetime.now(dt.UTC).isoformat(),'inputRun':39214475581,'inputFiles':{n:{'bytes':len(v),'sha256':sha(v)} for n,v in raw.items()},'outputHTML':{'bytes':len(html.encode()),'sha256':sha(html.encode())},'actualDataAsOf':D['meta']['asOfByMarket'],'priceDateRange':D['meta']['priceDateRange'],'sourceFixedClock':receipt['fixedClock'],'coverage':counts,'dataUnchanged':True,'checks':[],'screenshots':{},'browserErrors':[],'blockedRequests':[],'status':'pending_browser'}
 dump(args.out/'interaction-checks.json',report)
 from playwright.sync_api import sync_playwright
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   if self.path!='/review':self.send_error(404);return
   self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(html.encode())
  def log_message(self,*args):pass
 server=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}/review'
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
   page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1,reduced_motion='reduce')
   page.on('pageerror',lambda e:report['browserErrors'].append(str(e)))
   def route(r):
    if r.request.url==url:r.continue_()
    else:report['blockedRequests'].append(r.request.url);r.abort()
   page.route('**/*',route);page.goto(url,wait_until='networkidle')
   def shot(name):
    f=args.out/(name+'.png');page.screenshot(path=str(f));report['screenshots'][f.name]={'bytes':f.stat().st_size,'sha256':sha(f.read_bytes())}
   def click(group,value):page.locator('#'+group+' button[data-v='+json.dumps(value)+']').click()
   def rows():return page.locator('#tbl tbody tr[data-co]').evaluate_all('(xs)=>xs.map(x=>x.dataset.co)')
   def expected(ind,mkt):return sorted(c['id'] for c in D['companies'] if (ind=='all' or c['ind']==ind) and (mkt=='all' or (c['mkt'] not in ('A股','港股','美股') if mkt=='其他' else c['mkt']==mkt)))
   assert '441/477' in page.locator('#dataStatus').inner_text();shot('desktop-overview')
   industries=page.locator('#indSeg button').evaluate_all('(xs)=>xs.map(x=>x.dataset.v)');markets=page.locator('#mktSeg button').evaluate_all('(xs)=>xs.map(x=>x.dataset.v)')
   empty=0
   for ind in industries:
    for mkt in markets:
     click('indSeg',ind);click('mktSeg',mkt);click('viewSeg','table');ids=rows();want=expected(ind,mkt);assert sorted(ids)==want
     if not want:empty+=1;assert '无匹配公司' in page.locator('#tbl').inner_text()
     click('viewSeg','map');mapids=page.locator('#mapTiles .tile:not(.gone)').evaluate_all('(xs)=>xs.map(x=>x.dataset.co)');assert sorted(mapids)==want
     if not want:assert '无匹配公司' in page.locator('#mapLabels').inner_text()
     report['checks'].append({'filter':[ind,mkt],'tableAndMapIdsEqual':True,'count':len(want)})
   report['emptyFilterCombinationsTested']=empty
   click('indSeg','all');click('mktSeg','all');click('viewSeg','table')
   byid={c['id']:c for c in D['companies']}
   for key in ('r5','r20','r60','ytd','dd52','revg','earng','gm','pe','mcapUSD','next'):
    for _ in range(2):
     header=page.locator('th[data-sort='+json.dumps(key)+']');header.click();direction=-1 if '↓' in header.inner_text() else 1
     values=[None if key in ('revg','earng','gm') and byid[i]['financialPartial'] else byid[i].get(key) for i in rows()]
     present=[v for v in values if v is not None and v!=''];assert values[:len(present)]==present
     assert present==sorted(present,reverse=direction==-1)
     report['checks'].append({'sort':key,'direction':direction,'missingLast':True,'valid':len(present)})
   shot('desktop-table')
   for metric in ('r5','r20','r60','ytd','dd52','revg','earng'):
    click('metricSeg',metric);click('viewSeg','table')
    ix=page.locator('th').evaluate_all('(xs,key)=>xs.findIndex(x=>x.dataset.sort===key)',metric)
    texts=page.locator('#tbl tbody tr[data-co]').evaluate_all('(xs,ix)=>Object.fromEntries(xs.map(x=>[x.dataset.co,x.children[ix].querySelector(".num").textContent]))',ix)
    click('viewSeg','map');shown=page.locator('#mapTiles .tile:not(.gone)').evaluate_all('(xs)=>xs.filter(x=>x.querySelector(".tv")).map(x=>[x.dataset.co,x.querySelector(".tv").textContent])')
    assert all(texts[i]==v for i,v in shown);report['checks'].append({'metric':metric,'tableMapValuesEqual':True,'visibleTilesCompared':len(shown)})
   click('viewSeg','table')
   for symbol,name,need in [('LITE','lite','亏损 · 不适用'),('000660.KS','sk-hynix','暂未取得'),('688825.SS','cxmt','上市时间不足 · 可用 55 个交易日')]:
    c=next(c for c in D['companies'] if c['sym']==symbol);page.locator('#tbl tr[data-co='+json.dumps(c['id'])+']').click();text=page.locator('#drawer').inner_text();assert need in text
    assert '收盘折线' in text
    if c['mcapEstimated']:assert '≈' in text and c['provenance']['valuation']['fx']['asOf'] in text and '本币市值' in text
    shot('desktop-'+name);page.locator('#dwClose').click();report['checks'].append({'drawer':symbol,'requiredReasonVisible':need})
   page.locator('#openPalette').click();page.locator('#pq').fill('NO_MATCH_39214475581');assert page.locator('.pempty').is_visible();page.keyboard.press('Escape');report['checks'].append({'searchEmptyResult':True})
   before=page.locator('html').get_attribute('data-theme');page.locator('#themeBtn').click();theme=page.locator('html').get_attribute('data-theme');assert theme!=before
   before=page.locator('html').get_attribute('data-conv');page.locator('#convBtn').click();conv=page.locator('html').get_attribute('data-conv');assert conv!=before
   page.reload(wait_until='networkidle');assert page.locator('html').get_attribute('data-theme')==theme and page.locator('html').get_attribute('data-conv')==conv
   assert page.evaluate('localStorage.getItem("ar-theme")')==theme and page.evaluate('localStorage.getItem("ar-conv")')==conv
   report['checks'].append({'themeAndColorReloadPersistence':True});shot('desktop-persisted-theme')
   page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
   assert page.evaluate('document.documentElement.scrollWidth')<=390
   click('viewSeg','table');c=next(c for c in D['companies'] if c['sym']=='688825.SS');page.locator('#tbl tr[data-co='+json.dumps(c['id'])+']').click()
   assert '上市时间不足 · 可用 55 个交易日' in page.locator('#drawer').inner_text();assert page.locator('#drawer').bounding_box()['width']<=390
   shot('mobile-cxmt');page.locator('#dwClose').click();page.locator('#dataDetails summary').click();assert page.locator('#dataDetails').get_attribute('open') is not None
   assert '暂未取得表示当前快照没有有效值' in page.locator('#dataDetails').inner_text();shot('mobile-data-details')
   assert not report['browserErrors'];report['checks'].append({'narrowWidth':390,'noPageOverflow':True,'detailsAndMissingReasonsVisible':True});browser.close()
  report['status']='passed'
 except Exception as exc:
  report['status']='failed_or_blocked';report['failureType']=type(exc).__name__;raise
 finally:
  server.shutdown();report['finishedAt']=dt.datetime.now(dt.UTC).isoformat();dump(args.out/'interaction-checks.json',report)
 print(json.dumps({'status':report['status'],'checks':len(report['checks']),'htmlSHA256':report['outputHTML']['sha256']},ensure_ascii=False))
if __name__=='__main__':main()
