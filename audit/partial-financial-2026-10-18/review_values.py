"""Recalculate the two limited disclosures from downloaded public report amounts."""
import datetime as dt
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
receipt=json.loads((HERE/'source-access.json').read_text())
rows={r['id']:r for r in receipt['reports']}
need={
 'KBL-results':['14,903,809','9,588,032','10,323,576','2,886,561','933,317','24 August 2026'],
 'KBL-interim':['14,903,809','9,588,032','10,323,576','2,886,561','933,317'],
 'DZSK-9M-preliminary':['784,094.79','154,412.46','初步','未经会计师事务所审计'],
 'DZSK-H1':['4,984,920,813.21','956,862,424.74'],
 'DZSK-2025Q3':['1,520,984,069.00','228,435,144.32']}
reports=[]
for key,amounts in need.items():
 row=rows[key];assert row['httpStatus']==200 and row['status']=='parsed_requires_content_review'
 text=(Path('/tmp/radar-public-financial-sources')/(row['key']+'.txt')).read_text()
 for value in amounts:assert value in text,(key,value)
 # Persist only relevant statement pages; no private inputs or HTTP secrets.
 pages=text.split('\f');selected=[]
 for i,page in enumerate(pages):
  if (key=='DZSK-H1' and i<8 and any(v in page for v in amounts)) or (key!='DZSK-H1' and any(v in page for v in amounts)):
   selected.append({'pdfPage':i+1,'text':page})
 if key=='KBL-interim':selected=selected[:1]
 if key=='KBL-results':selected=[p for p in selected if 'Revenue' in p['text'] or '24 August 2026' in p['text']][:2]
 if key=='DZSK-2025Q3':selected=selected[:1]
 reports.append({'id':key,'url':row['url'],'httpBodySHA256':row['sha256'],'receivedAt':row['finishedAt'],'amountsVerified':amounts,'pages':selected})
krev,kprev,kprofit,kprofitprev,kcost=map(D,['14903809','9588032','2886561','933317','10323576'])
drev=D('784094.79')*10000-D('4984920813.21');dprofit=D('154412.46')*10000-D('956862424.74')
percent=lambda v:float(v.quantize(D('.000001')))
values={
 'KBL':{'revenue_yoy':percent((krev/kprev-1)*100),'profit_yoy':percent((kprofit/kprofitprev-1)*100),'gross_margin':percent((krev-kcost)/krev*100)},
 'DZSK':{'revenue_yoy':percent((drev/D('1520984069')-1)*100),'profit_yoy':percent((dprofit/D('228435144.32')-1)*100),'gross_margin':None}}
assert values=={'KBL':{'revenue_yoy':55.441795,'profit_yoy':209.279805,'gross_margin':30.731963},'DZSK':{'revenue_yoy':87.774951,'profit_yoy':157.080484,'gross_margin':None}}
evidence={'checkedAt':dt.datetime.now(dt.UTC).isoformat(),'purpose':'Two explicitly approved limited disclosures; not complete quarterly financial scoring',
 'reports':reports,'values':values,'derivations':{
 'KBL':{'units':'HKD thousands','period':'2026H1 cumulative','revenue':str(krev),'priorRevenue':str(kprev),'parentProfit':str(kprofit),'priorParentProfit':str(kprofitprev),'cost':str(kcost),'method':'H1 revenue and parent-profit YoY; (H1 revenue-H1 cost)/H1 revenue'},
 'DZSK':{'units':'CNY yuan (9M bulletin in 10,000 yuan converted first)','period':'2026Q3 preliminary difference','revenue':str(drev),'parentProfit':str(dprofit),'priorQ3Revenue':'1520984069.00','priorQ3ParentProfit':'228435144.32','method':'2026 9M preliminary bulletin minus 2026 H1; compare with explicitly reported 2025 Q3 single-quarter amounts','cost':None,'grossMargin':None}},
 'limitations':['KBL is H1 cumulative, not a single quarter; exclude complete score and normal growth ranking.','DZSK is preliminary 9M minus H1, unaudited and potentially revised; no disclosed cost, gross margin stays null; exclude complete score and normal growth ranking.','Parent reported no formal Q3 report found in the directory checked; this is not evidence that no report exists anywhere. Full KBL interim publication date 2026-09-18 is parent-supplied; earliest results dated 2026-08-24 verified in the PDF.']}
(HERE/'public-evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'values':values,'evidenceSHA256':hashlib.sha256((HERE/'public-evidence.json').read_bytes()).hexdigest(),'reports':len(reports),'pages':sum(len(r['pages']) for r in reports)},indent=2))
