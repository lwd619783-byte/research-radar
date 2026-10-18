"""Render real fetched values for LOCAL review, while preserving release blockers."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'radar/scripts'))
import build
from integrity import release_blockers
HERE=Path(__file__).resolve().parent
now=dt.datetime.now(build.BJ)
data,report=build.load_and_validate(build.RADAR,ROOT,now.date())
assert not report.errors,report.errors
mk=json.loads(Path('/tmp/radar-live-market.json').read_text())
D,stale,missing=build.assemble(data,mk,mk,now)
cs=D['companies']
summary=dict(checkedAt=now.isoformat(),marketSnapshotSHA256=hashlib.sha256(Path('/tmp/radar-live-market.json').read_bytes()).hexdigest(),
             asOf=D['meta']['asOf'],companies=len(cs),missingDaily=len(missing),staleDaily=len(stale),
             financialVerified=sum(c['provenance']['financial']['status']=='verified' for c in cs),
             financialComplete=sum(all(c[k] is not None for k in ('revg','earng','gm')) for c in cs),
             financialSignalEligible=sum(c['financialSignalEligible'] for c in cs),
             financialMissing=[c['id'] for c in cs if c['provenance']['financial']['status']!='verified'],
             mcapAvailable=sum(c['mcapUSD'] is not None for c in cs),
             sameDateFx=sum(c['provenance']['valuation']['fx'] is not None and c['provenance']['valuation']['fx']['asOf']==c['ld'] for c in cs),
             fx=D['meta']['fxProvenance'],blockers=release_blockers(D),
             shortHistory=[{'id':c['id'],**c['history']} for c in cs if c['history'].get('days',0)<731],
             missingPE=[{'id':c['id'],'status':c['provenance']['valuation']['peStatus']} for c in cs if c['pe'] is None],
             indicesAvailable=len(D['indices']),issues=D['meta']['issues'],
             ratioAvailable=D['ratio'] is not None)
assert summary['financialVerified']==40
assert summary['financialComplete']==37
assert summary['sameDateFx']==summary['mcapAvailable']==42
assert sorted(summary['financialMissing'])==['DZSK','KBL']
assert summary['blockers']==['financial_evidence_incomplete']
(HERE/'integrated-data-review.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
# Explicit local review rendering is not build.main and does not update any
# production cache/fingerprint. Even this reviewed HTML stays release-blocked.
D['meta']['reviewPreview']=True
D['meta']['blockers'].append('local_review_not_publishable')
Path('/tmp/radar-reviewed-data.json').write_text(json.dumps(D,ensure_ascii=False))
build.render(D,Path('/tmp/radar-desktop-review/after'))
print(json.dumps({k:v for k,v in summary.items() if k not in ('issues','fx')},ensure_ascii=False,indent=2))
