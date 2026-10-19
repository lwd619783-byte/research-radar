"""Real Chromium screenshots of the labeled OFFLINE mixed-date replay only."""
import datetime as dt,hashlib,json,threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE=Path(__file__).resolve().parent
html=Path('/tmp/radar-latest-replay.html').read_bytes()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path!='/review':self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(html)
 def log_message(self,*args):pass
server=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}/review';errors=[];blocked=[];checks={}
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1,reduced_motion='reduce')
 page.on('pageerror',lambda e:errors.append(str(e)))
 def route(r):
  if r.request.url==url:r.continue_()
  else:blocked.append(r.request.url);r.abort()
 page.route('**/*',route);page.goto(url,wait_until='networkidle');page.wait_for_timeout(700)
 checks['title']=page.title();checks['bodyWidth']=page.evaluate('document.body.scrollWidth');checks['viewportWidth']=1440
 checks['tickerLabel']=page.locator('#tickerLabel').inner_text()
 page.screenshot(path=str(HERE/'desktop-overview.png'))
 page.locator('#viewSeg').get_by_text('列表',exact=True).click();page.locator('#leaders').scroll_into_view_if_needed();page.wait_for_timeout(300)
 checks['tableRows']=page.locator('#tbl tbody tr').count()
 page.screenshot(path=str(HERE/'desktop-table.png'))
 for symbol,name in [('688825.SS','cxmt'),('LITE','lite'),('000660.KS','sk-hynix')]:
  cid=page.evaluate('(sym)=>DATA.companies.find(c=>c.sym===sym).id',symbol)
  page.locator('#tbl tr[data-co="'+cid+'"]').click();page.wait_for_timeout(300)
  checks[name]=page.locator('#drawer').inner_text()
  page.screenshot(path=str(HERE/f'desktop-{name}.png'))
  page.locator('#dwClose').click()
 browser.close()
server.shutdown()
checks.update(classification='OFFLINE MIXED-DATE REPLAY — not a fresh full market run',capturedAt=dt.datetime.now(dt.UTC).isoformat(),htmlSHA256=hashlib.sha256(html).hexdigest(),browserErrors=errors,blockedNonReviewRequests=blocked)
(HERE/'desktop-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
assert not errors,errors
assert checks['bodyWidth']==1440,checks['bodyWidth']
assert checks['tableRows']==42
assert 'EPS≤0' in checks['lite']
assert 'PE(TTM) 缺失' in checks['sk-hynix']
assert '52周数据不足' in checks['cxmt'] and '2年·不足' in checks['cxmt']
print(json.dumps({'browserErrors':errors,'tableRows':checks['tableRows'],'pageWidth':checks['bodyWidth'],'screenshots':5}))
