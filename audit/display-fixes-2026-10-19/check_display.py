"""Compare actual Chromium renders on identical offline data and edge variants."""
import copy
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import re
import sys
import threading
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
SHOTS=HERE/'screenshots';SHOTS.mkdir(exist_ok=True)
D=json.loads((ROOT/'audit/offline-page-acceptance-2026-10-19/test-data.json').read_text())
AFTER=(HERE/'after.html').read_text()
keys=('price','r5','r20','r60','ytd','dd52','revg','earng','gm','pe','mcapUSD')
missing=copy.deepcopy(D)
for c in missing['companies']:
 for k in keys:c[k]=None
zero=copy.deepcopy(missing);zero['companies'][0]['r20']=0;zero['companies'][0]['revg']=0
zero['companies'][0]['sc']=[]
sys.path.insert(0,str(ROOT/'radar/scripts'));import build
cfg,_=build.load_and_validate(build.RADAR,ROOT,dt.date(2026,10,19))
missing['indices']=[]
missing['meta']['issues']=[x for x in missing['meta']['issues'] if x.get('kind')!='index']+[{'kind':'index','symbol':x['symbol'],'status':'synthetic_missing'} for x in cfg['config']['indices']]
variants={'all-missing':missing,'zero-vs-null':zero}
assets={'/before.html':(HERE/'before.html').read_bytes(),'/after.html':AFTER.encode()}
for key,data in variants.items():
 blob=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
 assets['/'+key+'.html']=re.sub(r'<script>const DATA=.*?;</script>',lambda m:'<script>const DATA='+blob+';</script>',AFTER,count=1,flags=re.S).encode()
class OnlyPreview(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path not in assets:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(assets[self.path])
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),OnlyPreview);threading.Thread(target=server.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(server.server_port)
checks=[];errors=[];outbound=[];observed={}
def check(name,ok,evidence):checks.append({'check':name,'passed':bool(ok),'evidence':evidence})
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1,reduced_motion='reduce')
 def route(r):
  if r.request.url in {base+k for k in assets}:r.continue_()
  else:outbound.append(r.request.url.split('?')[0]);r.abort()
 context.route('**/*',route)
 def load(name):
  page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(base+'/'+name+'.html');page.wait_for_selector('#mapTiles .tile');page.wait_for_timeout(1000);return page
 def shot(page,name):
  assert page.locator('#audit-fixture-notice').is_visible()
  page.screenshot(path=str(SHOTS/name),animations='disabled')
 def columns(page):return page.locator('#tbl th').evaluate_all('(es)=>es.map(e=>e.dataset.sort)')
 def rows(page):return page.locator('#tbl tbody tr').evaluate_all('(es)=>es.map(e=>({id:e.dataset.co,cells:[...e.querySelectorAll("td")].map(x=>x.innerText)}))')
 def expected_count(data,key):return sum(isinstance(c.get(key),(int,float)) and not (c.get('financialPartial') and key in ('revg','earng','gm')) for c in data)
 def header_counts(page,data,name):
  for key in ('r5','r20','r60','ytd','dd52','revg','earng','gm','pe','mcapUSD'):
   expected='有效 '+str(expected_count(data,key))+'/'+str(len(data))
   actual=page.locator('#tbl th[data-sort="'+key+'"] .muted').inner_text()
   check(name+'_'+key,actual==expected,actual)
 for version in ('before','after'):
  page=load(version);data={}
  data['tickerLabel']=page.locator('#tickerLabel').inner_text();data['tickerText']=page.locator('#tickerTrack').inner_text()
  data['topCoverage']=page.locator('#topCard .tstat .l').all_inner_texts()
  shot(page,version+'-01-overview-indices.png')
  if version=='after':
   check('index_coverage_5_of_8','指数有效 5/8' in data['tickerLabel'],data['tickerLabel'])
   check('three_index_gaps_explicit',all(code in data['tickerText'] for code in ('399006.SZ','000922.SS','HSTECH.HK')),page.locator('#tickerTrack .idx-gap').first.inner_text())
   cos=[c for c in D['companies'] if c['ind']=='AI网络与光互连']
   nums=[sum(c[k] is not None for c in cos) for k in ('r20','dd52')]+[sum(c['financialRevenueComparable'] and c['revg'] is not None for c in cos)]
   check('hero_metric_specific_counts',all('有效 '+str(n)+'/'+str(len(cos)) in t for n,t in zip(nums,data['topCoverage'])),data['topCoverage'])
  page.locator('#thermoCard').scroll_into_view_if_needed();page.wait_for_timeout(100)
  data['ratio']=page.locator('#thermoCard').inner_text();shot(page,version+'-02-ratio.png')
  if version=='after':check('ratio_factual_empty_state','当前快照无可用比值数据' in data['ratio'] and '恢复' not in data['ratio'] and '不在极端区' not in data['ratio'] and page.locator('#thermoCard .gauge,#thermoCard .th-txt').count()==0,data['ratio'])
  page.locator('#viewSeg button[data-v="table"]').click();page.locator('#mktSeg button[data-v="A股"]').click()
  page.locator('#tableCard').scroll_into_view_if_needed();page.wait_for_timeout(100)
  data['AshareSub']=page.locator('#leadSub').inner_text();data['shortRow']=page.locator('#tbl tbody tr[data-co="CXMT"]').inner_text()
  shot(page,version+'-03-filter-short-history.png')
  page.locator('#tbl tbody tr[data-co="CXMT"]').scroll_into_view_if_needed()
  shot(page,version+'-03b-cxmt-actual-history.png')
  if version=='after':
   expected=[c for c in D['companies'] if c['mkt']=='A股'];header_counts(page,expected,'Ashare')
   check('Ashare_summary_zero_of_22','市值有效 0/22' in data['AshareSub'] and 'PE有效 0/22' in data['AshareSub'],data['AshareSub'])
   check('short_row_actual_54','实际 54 个交易日 · 短历史' in data['shortRow'],data['shortRow'])
  page.locator('#mktSeg button[data-v="all"]').click()
  if version=='after':
   header_counts(page,D['companies'],'all')
   check('all_summary_17_and_16','市值有效 17/42' in page.locator('#leadSub').inner_text() and 'PE有效 16/42' in page.locator('#leadSub').inner_text(),page.locator('#leadSub').inner_text())
   byid={c['id']:c for c in D['companies']};cols=columns(page)
   for key in ('mcapUSD','pe','revg','earng','gm'):
    for _ in range(2):
     page.locator('#tbl th[data-sort="'+key+'"]').click();rs=rows(page);i=cols.index(key)
     nulls=[n for n,r in enumerate(rs) if r['cells'][i]=='—'];vals=[byid[r['id']][key] for r in rs if r['cells'][i]!='—']
     descending='↓' in page.locator('#tbl th[data-sort="'+key+'"]').inner_text()
     check('sort_'+key+str(descending),(not nulls or nulls==list(range(nulls[0],len(rs)))) and vals==sorted(vals,reverse=descending),{'valid':len(vals),'missing':len(nulls)})
   for metric in ('revg','earng','gm'):
    i=cols.index(metric)
    check('partial_excluded_'+metric,all(next(r for r in rows(page) if r['id']==cid)['cells'][i]=='—' for cid in ('KBL','DZSK')),{'partialIDs':['KBL','DZSK']})
   for market in ('港股','美股','其他'):
    page.locator('#mktSeg button[data-v="'+market+'"]').click()
    expected=[c for c in D['companies'] if (c['mkt'] not in ('A股','港股','美股') if market=='其他' else c['mkt']==market)]
    header_counts(page,expected,market)
   page.locator('#mktSeg button[data-v="all"]').click()
  aggregates=[]
  for industry,label in (('AI核心半导体','semiconductor'),('PCB与覆铜板','pcb'),('AI网络与光互连','network'),('电力与数据中心','power')):
   page.locator('#indList [data-pick="'+industry+'"]').click();page.wait_for_timeout(150)
   cos=[c for c in D['companies'] if c['ind']==industry]
   pools=[[c['r20'] for c in cos if c['r20'] is not None],[c['dd52'] for c in cos if c['dd52'] is not None],[c['revg'] for c in cos if c['financialRevenueComparable'] and c['revg'] is not None]]
   labels=page.locator('#indDetail .rstat .l').all_inner_texts();values=page.locator('#indDetail .rstat .v').all_inner_texts()
   aggregates.append({'industry':industry,'labels':labels,'values':values,'valid':[len(v) for v in pools],'total':len(cos)})
   if version=='after':
    check('aggregate_counts_'+label,all('有效 '+str(len(pool))+'/'+str(len(cos)) in text for pool,text in zip(pools,labels)),aggregates[-1])
   if label in ('semiconductor','pcb'):
    page.locator('#indDetail').scroll_into_view_if_needed();shot(page,version+'-04-'+label+'.png')
  data['aggregates']=aggregates
  data['layout']=page.evaluate('()=>({sections:[...document.querySelectorAll("main > section")].map(e=>e.id),cards:document.querySelectorAll(".bento > article").length,overflow:document.documentElement.scrollWidth>innerWidth})')
  observed[version]=data;page.close()
 check('aggregate_values_unchanged',all(a['values']==b['values'] for a,b in zip(observed['before']['aggregates'],observed['after']['aggregates'])),observed['after']['aggregates'])
 check('structure_and_viewport_unchanged',observed['before']['layout']==observed['after']['layout'] and not observed['after']['layout']['overflow'],observed['after']['layout'])
 # Empty intersection of real existing filters, with all denominators 0/0.
 page=load('after');page.locator('#viewSeg button[data-v="table"]').click()
 page.locator('#indSeg button[data-v="PCB与覆铜板"]').click();page.locator('#mktSeg button[data-v="美股"]').click()
 check('empty_filter_rows',page.locator('#tbl tbody tr').count()==0,page.locator('#leadSub').inner_text());header_counts(page,[],'empty_filter')
 page.locator('#tableCard').scroll_into_view_if_needed();shot(page,'after-05-empty-filter.png');page.close()
 for variant,data in variants.items():
  page=load(variant);page.locator('#viewSeg button[data-v="table"]').click();header_counts(page,data['companies'],variant)
  page.locator('#tableCard').scroll_into_view_if_needed();shot(page,'after-06-'+variant+'.png')
  if variant=='all-missing':
   check('all_indices_missing_0_of_8','指数有效 0/8' in page.locator('#tickerLabel').inner_text(),page.locator('#tickerLabel').inner_text())
   check('all_missing_table_dashes',all(r['cells'][columns(page).index('mcapUSD')]=='—' for r in rows(page)),{'rows':len(rows(page))})
   page.locator('#indList [data-pick="AI核心半导体"]').click()
   check('all_missing_aggregate_not_zero',page.locator('#indDetail .rstat .v').all_inner_texts()==['—']*3 and all('有效 0/9' in x for x in page.locator('#indDetail .rstat .l').all_inner_texts()),page.locator('#indDetail .rstats').inner_text())
  else:
   cid=data['companies'][0]['id'];i=columns(page).index('r20');row=next(r for r in rows(page) if r['id']==cid)
   check('true_zero_displayed_as_zero_percent',row['cells'][i]=='0.0%' and '实际 0 个交易日 · 短历史' in row['cells'][3],row)
   for _ in range(2):
    page.locator('#tbl th[data-sort="r20"]').click();rs=rows(page)
    check('true_zero_sorts_before_null_'+str(_),rs[0]['id']==cid and all(r['cells'][i]=='—' for r in rs[1:]),{'first':rs[0]['id']})
  page.close()
 check('no_runtime_or_network_errors',not errors and not outbound,{'pageErrors':errors,'externalRequests':outbound})
 browser.close()
server.shutdown();server.server_close()
receipt={'checkedAt':dt.datetime.now(dt.UTC).isoformat(),'dataClassification':'Same synthetic/old-sample fixture as prior audit, plus explicitly synthetic missing/zero edge variants; not real Actions DATA','browser':'Installed Chromium via Playwright; loopback-only assets and CSP, no external requests','viewport':{'width':1440,'height':1000},'checks':checks,'observed':observed,'edgeVariants':{'all-missing':'all displayed numeric metrics null; all eight configured indices unavailable','zero-vs-null':'same numeric nulls except first company r20/revg are real numeric zero; its history is empty'},'screenshots':{f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in SHOTS.glob('*.png')}}
(HERE/'browser-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks':len(checks),'passed':sum(x['passed'] for x in checks),'failed':[x for x in checks if not x['passed']],'screenshots':len(receipt['screenshots'])},ensure_ascii=False,indent=2))
if not all(x['passed'] for x in checks):raise SystemExit(1)
