"""Actual offline Chromium rendering and interactions; no production edits."""
import datetime as dt
import hashlib
import json
import statistics
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE=Path(__file__).resolve().parent;SHOTS=HERE/'screenshots';SHOTS.mkdir(exist_ok=True)
D=json.loads((HERE/'test-data.json').read_text());BY={c['id']:c for c in D['companies']}
checks=[];findings=[];errors=[];outbound=[];details={}
class PreviewOnly(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path not in ('/','/preview.html'):
   self.send_error(404);return
  blob=(HERE/'preview.html').read_bytes()
  self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8')
  self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(blob)
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),PreviewOnly)
threading.Thread(target=server.serve_forever,daemon=True).start()
url='http://127.0.0.1:'+str(server.server_port)+'/preview.html'
def check(name,ok,evidence):checks.append({'check':name,'status':'pass' if ok else 'fail','evidence':evidence})
def finding(code,scope,evidence):findings.append({'id':code,'scope':scope,'evidence':evidence,'productionChanged':False})

with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1,reduced_motion='reduce')
 def route(r):
  if r.request.url != url:
   outbound.append(r.request.url.split('?')[0]);r.abort()
  else:r.continue_()
 context.route('**/*',route)
 page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(url);page.wait_for_selector('#mapTiles .tile');page.wait_for_timeout(1100)
 def shot(name):
  assert page.locator('#audit-fixture-notice').is_visible()
  page.screenshot(path=str(SHOTS/name),animations='disabled')
 def columns():return page.locator('#tbl thead th').evaluate_all('(els)=>els.map(e=>e.dataset.sort)')
 def table_rows():return page.locator('#tbl tbody tr').evaluate_all('(els)=>els.map(e=>({id:e.dataset.co,cells:[...e.querySelectorAll("td")].map(x=>x.innerText)}))')
 def open_drawer(cid):
  page.locator('[data-co="'+cid+'"]').first.evaluate('(el)=>el.click()');page.wait_for_timeout(200)
  page.locator('#drawer').evaluate('(el)=>el.scrollTop=0')
 def close_drawer():page.locator('#dwClose').click()
 details['date']={'hero':page.locator('#heroDate').inner_text(),'ticker':page.locator('#tickerLabel').inner_text()}
 check('snapshot_date_not_generated_date','10/16 收盘' in details['date']['hero'] and '10/16 收盘' in details['date']['ticker'] and '实时' not in details['date']['hero'],details['date'])
 shot('01-overview-test-data.png')
 page.locator('#thermoCard').scroll_into_view_if_needed();page.wait_for_timeout(200)
 thermo=page.locator('#thermoCard').inner_text();details['ratioText']=thermo
 check('missing_ratio_has_no_old_value_chart_or_fixed_judgment','暂不可用' in thermo and page.locator('#thermoCard svg.gauge,#thermoCard .gauge,#thermoCard .th-txt,#thermoCard .th-rng').count()==0 and '不在极端区' not in thermo,thermo)
 if '自动恢复' in thermo:finding('F3','ratio 缺失提示作出恢复承诺',thermo)
 shot('02-ratio-unavailable.png')
 ticker=page.locator('#tickerTrack .idx').all_inner_texts();names=[i['name'] for i in D['indices']]
 check('only_available_indices_rendered',len(ticker)==10 and all(any(name in row for name in names) for row in ticker),{'uniqueAvailable':5,'duplicatedForTicker':len(ticker),'names':names})
 finding('F2','缺失指数没有显式覆盖或缺项提示',{'tickerAvailable':names,'tickerLabel':details['date']['ticker'],'configured':8,'displayed':5,'note':'5/8 is the explicit fixture assumption; original receipt had no assembled list.'})
 # Exercise all sort directions and every table valuation cell.
 page.locator('#viewSeg button[data-v="table"]').click();page.locator('#leaders').scroll_into_view_if_needed();page.wait_for_timeout(200)
 cols=columns();rows=table_rows();details['tableHeaders']=page.locator('#tbl thead').inner_text()
 for key in ('mcapUSD','pe'):
  i=cols.index(key);missing=[r for r in rows if BY[r['id']][key] is None]
  check(key+'_missing_cells_are_dashes',all(r['cells'][i]=='—' for r in missing),{'missingCount':len(missing),'ids':[r['id'] for r in missing]})
 sort_results=[]
 for key in ('mcapUSD','pe','revg','earng','gm'):
  for _ in range(2):
   page.locator('#tbl th[data-sort="'+key+'"]').click();rs=table_rows();i=cols.index(key)
   nulls=[n for n,r in enumerate(rs) if r['cells'][i]=='—']
   tail=not nulls or nulls==list(range(nulls[0],len(rs)))
   descending='↓' in page.locator('#tbl th[data-sort="'+key+'"]').inner_text()
   values=[]
   for row in rs:
    if row['cells'][i]=='—':continue
    values.append(BY[row['id']][key])
   ordered=values==sorted(values,reverse=descending)
   partial_ok=all(next(r for r in rs if r['id']==cid)['cells'][i]=='—' for cid in ('KBL','DZSK')) if key in ('revg','earng','gm') else True
   record={'key':key,'direction':'descending' if descending else 'ascending','numericCount':len(values),'missingCount':len(nulls),'nullsLast':tail,'numericallyOrdered':ordered,'partialExcluded':partial_ok}
   sort_results.append(record);check('sort_'+key+'_'+record['direction'],tail and ordered and partial_ok,record)
 details['sorts']=sort_results
 page.locator('#tbl th[data-sort="mcapUSD"]').click()
 page.locator('#tableCard').scroll_into_view_if_needed();page.wait_for_timeout(150);shot('03-table-sort-and-missing-values.png')
 # A-share filter has 22 missing valuations. No zeros are introduced by filtering.
 filtered=[]
 for market in ('A股','港股','美股','其他','all'):
  page.locator('#mktSeg button[data-v="'+market+'"]').click();rs=table_rows()
  expected=[c for c in D['companies'] if market=='all' or (c['mkt'] not in ('A股','港股','美股') if market=='其他' else c['mkt']==market)]
  ok={r['id'] for r in rs}=={c['id'] for c in expected}
  nmc=sum(c['mcapUSD'] is not None for c in expected);npe=sum(c['pe'] is not None for c in expected)
  filtered.append({'market':market,'rows':len(rs),'marketCapAvailable':nmc,'peAvailable':npe})
  check('market_filter_'+market,ok,filtered[-1])
  if market=='A股':
   check('A_share_filter_all_missing_valuation_stays_dash',all(r['cells'][cols.index('pe')]=='—' and r['cells'][cols.index('mcapUSD')]=='—' for r in rs),{'rows':len(rs)})
   page.locator('#tableCard').scroll_into_view_if_needed();shot('04-a-share-filter.png')
 details['marketFilters']=filtered
 details['coverageText']={'leadSub':page.locator('#leadSub').inner_text(),'tableFooter':page.locator('#sigLegend').inner_text(),'filterLabels':page.locator('#mktSeg').inner_text()}
 finding('F1','排序/筛选和聚合缺少逐指标有效覆盖分母',{'fixtureMarketCap':'17/42','fixturePE':'16/42','tableUI':details['coverageText'],'note':'Filters identify categories; they do not show current non-null/total counts.'})
 for industry in sorted({c['ind'] for c in D['companies']}):
  button=page.locator('#indSeg button').filter(has_text=industry)
  if button.count():
   button.click();rs=table_rows()
   check('industry_filter_'+industry,{r['id'] for r in rs}=={c['id'] for c in D['companies'] if c['ind']==industry},{'rows':len(rs)})
 page.locator('#indSeg button[data-v="all"]').click()
 # Drawers retain missingness, partial periods and short-history disclosures.
 for cid,name in (('SKH','05-missing-valuation-drawer.png'),('LITE','06-lite-missing-pe.png'),('CXMT','07-short-history.png'),('KBL','08-kbl-partial.png'),('DZSK','09-dzsk-partial.png')):
  open_drawer(cid);text=page.locator('#drawer').inner_text()
  if cid=='SKH':check('missing_valuation_drawer','市值约 —' in text and 'PE(TTM) 缺失' in text,{'id':cid,'text':text[:1300]})
  if cid=='LITE':check('LITE_PE_missing_not_zero','PE(TTM) 缺失' in text and page.locator('#drawer .mgrid.four .mt').last.locator('.v').inner_text()=='—',{'id':cid,'peCell':page.locator('#drawer .mgrid.four .mt').last.inner_text()})
  if cid=='CXMT':
   check('short_history_drawer','短历史 · 实际54日' in text and '2年·不足' in text and '52周数据不足' in text,{'id':cid,'text':text[:1300],'source':'54 is the older local fixture, not a run receipt selected count'})
  if cid in ('KBL','DZSK'):check(cid+'_partial_not_scored','部分披露 · 不评分' in text,{'id':cid,'label':page.locator('#drawer .dw-sec').inner_text()})
  shot(name);close_drawer()
 # Table sparkline still has a fixed 60-day header for the shorter row.
 cx=page.locator('#tbl tbody tr[data-co="CXMT"]');cxtext=cx.inner_text()
 details['shortTable']={'header':page.locator('#tbl thead').inner_text(),'row':cxtext}
 if '60日走势' in details['shortTable']['header'] and '短历史' not in cxtext:
  finding('F4','列表固定“60日走势”未对短历史行提示不足',{'header':'60日走势','row':cxtext,'fixtureHistoryCount':54})
 cx.scroll_into_view_if_needed();shot('10-short-history-table-label.png')
 # Browser-rendered industry aggregates must exclude missing observations and partials.
 aggregates=[]
 for industry in ('AI核心半导体','PCB与覆铜板'):
  page.locator('#indList [data-pick="'+industry+'"]').click();page.wait_for_timeout(120)
  cos=[c for c in D['companies'] if c['ind']==industry]
  pools=[[c['r20'] for c in cos if c['r20'] is not None],[c['dd52'] for c in cos if c['dd52'] is not None],[c['revg'] for c in cos if c['financialRevenueComparable'] and c['revg'] is not None]]
  expected=[statistics.mean(v) if n<2 else statistics.median(v) for n,v in enumerate(pools)]
  actual=page.locator('#indDetail .rstat .v').all_inner_texts()
  parsed=[float(t.replace('−','-').replace('+','').replace('%',''))/100 for t in actual]
  record={'industry':industry,'totalCompanies':len(cos),'validCounts':[len(v) for v in pools],'expected':expected,'rendered':actual,'caption':page.locator('#indDetail .rstats .hint').inner_text()}
  aggregates.append(record);check('aggregate_excludes_missing_and_partial_'+industry,all(abs(a-b)<=(.0051 if '.' not in t else .00051) for a,b,t in zip(parsed,expected,actual)),record)
  page.locator('#indDetail').scroll_into_view_if_needed();shot('11-aggregate-'+('semiconductor' if industry=='AI核心半导体' else 'pcb')+'.png')
 details['aggregates']=aggregates
 # Map placeholder areas are disclosed; no market-cap total or PE mean exists in this UI.
 page.locator('#viewSeg button[data-v="map"]').click();page.locator('#metricSeg button[data-v="revg"]').click()
 colors={cid:page.locator('#mapTiles [data-co="'+cid+'"]').evaluate('(e)=>e.style.backgroundColor') for cid in ('KBL','DZSK')}
 check('partial_heatmap_neutral',all(v=='rgb(42, 46, 57)' for v in colors.values()),colors)
 check('map_placeholder_area_disclosed','市值缺失用占位面积' in page.locator('#mapLegend').inner_text(),page.locator('#mapLegend').inner_text())
 page.locator('#mapCard').scroll_into_view_if_needed();shot('12-map-placeholders-and-partial.png')
 details['marketCapTotalAndPEMean']='No such aggregate component is present; not asserted as tested. Existing return means/revenue medians were numerically checked.'
 details['layout']=page.evaluate('()=>({sections:[...document.querySelectorAll("main > section")].map(e=>e.id),cards:document.querySelectorAll(".bento > article").length,overflow:document.documentElement.scrollWidth>innerWidth})')
 check('no_page_errors_or_external_requests',not errors and not outbound,{'pageErrors':errors,'blockedOutboundAttempts':outbound})
 check('production_section_structure_preserved',details['layout']['sections']==['overview','radar','choke','leaders','calendar'] and details['layout']['cards']==4 and not details['layout']['overflow'],details['layout'])
 browser.close()
server.shutdown();server.server_close()
receipt={'checkedAt':dt.datetime.now(dt.UTC).isoformat(),'browser':'Installed Chromium via Playwright; explicitly allowed loopback HTTP serving only the fixture; all other routes denied and CSP connect-src none','viewport':{'width':1440,'height':1000},'dataClassification':'SYNTHETIC COMPONENT TEST, not run 39190870708 rendered data','checks':checks,'findings':findings,'details':details,'productionFilesChanged':False,'screenshots':{f.name:{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in SHOTS.glob('*.png')}}
(HERE/'desktop-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checks':len(checks),'passed':sum(c['status']=='pass' for c in checks),'failed':[c['check'] for c in checks if c['status']=='fail'],'findings':findings,'screenshots':len(receipt['screenshots'])},ensure_ascii=False,indent=2))
