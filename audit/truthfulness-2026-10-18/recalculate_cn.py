import json,hashlib,re
from pathlib import Path
P=Path('audit/truthfulness-2026-10-18')
cs=json.loads((P/'financial-candidates-received.json').read_text())['candidates']
rows=[]
for c in cs:
 if c['currency']!='CNY' or c['id']=='CXMT': continue
 r={'id':c['id'],'reports':[]}
 for u in c['source_urls'][:2]:
  p=Path('/tmp/radar-public-financial-sources')/(hashlib.sha256(u.encode()).hexdigest()[:16]+'.txt')
  if not p.exists(): continue
  t=p.read_text();m=re.search('一、营业总收入',t)
  if not m: r['reports'].append({'missing':'income_table'});continue
  t=t[m.start():];end=re.search('母公司利润表',t);t=t[:end.start()] if end else t[:6000]
  numbers={}
  for k,pat in [('revenue','一、营业总收入'),('operating_revenue','其中：营业收入'),('cost','(?:其中：)?营业成本'),('profit','归属于母公司(?:所有者|股东)的净利润')]:
   m=re.search(pat,t)
   if m:
    snippet=t[m.end():m.end()+240]
    amounts=re.findall(r'-?\d[\d,]*\.\d{2}(?!\d)',snippet)
    numbers[k]=amounts[:2]
  r['reports'].append({'url':u,'values':numbers})
 if len(r['reports'])==2 and all(len(x.get('values',{}))==4 and all(len(v)==2 for v in x['values'].values()) for x in r['reports']):
  a,b=[{k:[float(n.replace(',','')) for n in v] for k,v in x['values'].items()} for x in r['reports']]
  q={k:[a[k][i]-b[k][i] for i in (0,1)] for k in a}
  r['quarter']=q
  r['computed']={'revenue_yoy':(q['revenue'][0]/q['revenue'][1]-1)*100,'profit_yoy':(q['profit'][0]/q['profit'][1]-1)*100,'gross_margin':(1-q['cost'][0]/q['operating_revenue'][0])*100}
  r['delta']={k:round(v-c['fin_schema_compatible_candidate'][k],6) for k,v in r['computed'].items()}
 rows.append(r)
 print(c['id'],json.dumps(r.get('computed') or r['reports'],ensure_ascii=False),r.get('delta'))
(P/'cn-quarter-recalculation.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
