"""Read only supplied public sources; deny/challenge stops that host. No adoption."""
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"): self.hidden+=1
        if tag in ("tr", "p", "div"): self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"): self.hidden=max(0,self.hidden-1)
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data.strip()+" ")

HERE = Path(__file__).resolve().parent
RAW = Path('/tmp/radar-public-financial-sources')
RAW.mkdir(exist_ok=True)
PACK = json.loads((HERE/'financial-candidates-received.json').read_text())
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args): return None

def group_fetch(item):
    host, urls = item
    rows, stopped = [], False
    op = urllib.request.build_opener(NoRedirect())
    for url in urls:
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        row = dict(url=url, key=key, startedAt=dt.datetime.now(dt.UTC).isoformat(), contentVerified=False)
        if stopped:
            row['status']='host_stopped_after_denial_or_challenge'; rows.append(row); continue
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'research-radar public financial verification'})
            with op.open(req,timeout=20) as r:
                body=r.read(12*1024*1024+1)
                row.update(httpStatus=r.status,bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
            if len(body)>12*1024*1024: raise ValueError('body_limit')
            if body.startswith(b'%PDF'):
                src=RAW/(key+'.pdf'); src.write_bytes(body)
                out=RAW/(key+'.txt')
                run=subprocess.run(['pdftotext','-layout',str(src),str(out)],capture_output=True)
                if run.returncode: raise ValueError('pdf_parse_failed')
                text=out.read_text(errors='replace')
                row['format']='pdf'
            else:
                parser=TextParser(); parser.feed(body.decode('utf-8',errors='replace'))
                text=''.join(parser.parts)
                (RAW/(key+'.txt')).write_text(text)
                row['format']='html'
            row['textCharacters']=len(text)
            challenge=any(x in text.lower() for x in ('verify you are human','access denied','just a moment','enable javascript and cookies','unusual traffic'))
            row['status']='challenge_stop' if challenge else 'parsed_requires_content_review'
            if challenge: stopped=True
        except urllib.error.HTTPError as e:
            row.update(httpStatus=e.code,status='http_error')
            if e.code in (401,403,451,429): stopped=True
        except Exception as e:
            row.update(status=type(e).__name__)
        row['finishedAt']=dt.datetime.now(dt.UTC).isoformat()
        rows.append(row)
    return rows

if __name__=='__main__':
    groups={}
    for c in PACK['candidates']:
        for url in c['source_urls']:
            host=urllib.parse.urlsplit(url).hostname
            group=groups.setdefault(host,[])
            if url not in group: group.append(url)
    results=[]
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(group_fetch,groups.items()):
            results.extend(result)
            print([(r['key'],r['status'],r.get('httpStatus')) for r in result],flush=True)
    receipt={'purpose':'source-access-and-parse-only-not-adoption','candidateCount':len(PACK['candidates']), 'sources':results}
    (HERE/'financial-source-access.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
