"""Read the five user-supplied public reports with the existing bounded reader."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('public_reader',HERE.parent/'truthfulness-2026-10-18/verify_financial_sources.py')
reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
SOURCES={
 'KBL-results':'https://www.kblaminates.com/en/upload/portal/20260824/202608241223596609.pdf',
 'KBL-interim':'https://www.kblaminates.com/en/upload/portal/20260918/202609180905142933.pdf',
 'DZSK-9M-preliminary':'https://static.cninfo.com.cn/finalpage/2026-10-15/1225606787.PDF',
 'DZSK-H1':'https://static.cninfo.com.cn/finalpage/2026-08-21/1225486321.PDF',
 'DZSK-2025Q3':'https://disc.static.szse.cn/disc/disk03/finalpage/2025-10-21/7573d795-1085-45c8-803c-511d9e66f2d4.PDF'}
if __name__=='__main__':
    groups={}
    for u in SOURCES.values():groups.setdefault(reader.urllib.parse.urlsplit(u).hostname,[]).append(u)
    start=dt.datetime.now(dt.UTC).isoformat();rows=[]
    with reader.cf.ThreadPoolExecutor(max_workers=3) as pool:
        for group in pool.map(reader.group_fetch,groups.items()):rows.extend(group)
    for row in rows:
        row['id']=next(k for k,v in SOURCES.items() if v==row['url'])
    (HERE/'source-access.json').write_text(json.dumps({'startedAt':start,'finishedAt':dt.datetime.now(dt.UTC).isoformat(),'reports':rows},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{'id':r['id'],'status':r['status'],'httpStatus':r.get('httpStatus'),'bytes':r.get('bytes'),'key':r['key']} for r in rows],indent=2))
