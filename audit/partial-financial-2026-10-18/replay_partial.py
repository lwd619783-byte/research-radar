"""Portable offline replay of real public market evidence; local build only."""
import contextlib
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'radar/scripts'))
import build
from integrity import release_blockers
FX=HERE.parent/'truthfulness-2026-10-18'
manifest=json.loads((FX/'fx-finality-capture.json').read_text())
raw=gzip.decompress((FX/'fixtures/market-finality.json.gz').read_bytes())
assert hashlib.sha256(raw).hexdigest()==manifest['files']['market-finality.json.gz']['uncompressedSHA256']
mk=json.loads(raw)
evidence=json.loads((HERE/'public-evidence.json').read_text())
replay_at=dt.datetime.fromisoformat(evidence['checkedAt'])
OUT=Path('/tmp/radar-partial-review');OUT.mkdir(exist_ok=True)
class Clock(dt.datetime):
    @classmethod
    def now(cls,tz=None):return replay_at.astimezone(tz) if tz else replay_at.replace(tzinfo=None)
results=[]
for force in (False,True):
    run=OUT/('force' if force else 'normal');run.mkdir(exist_ok=True)
    output=run/'gh-output.txt';output.write_text('')
    (run/'cache.json').unlink(missing_ok=True)  # Each replay begins with an isolated cold cache.
    args=['build.py','--cache',str(run/'cache.json'),'--out',str(run/'built'),'--audit-json',str(run/'build-report.json')]
    if force:args.append('--force')
    stream=io.StringIO()
    with patch.object(sys,'argv',args),patch.object(build.dt,'datetime',Clock), \
         patch.object(build,'fetch_all',return_value=(mk,['Recorded public snapshot replay; no new network request'])), \
         patch.dict(os.environ,{'GITHUB_OUTPUT':str(output),'GITHUB_STEP_SUMMARY':str(run/'summary.md')}),contextlib.redirect_stdout(stream):
        code=build.main()
    report=json.loads((run/'build-report.json').read_text());D=report['data']
    assert code==0 and report['blockers']==[]
    assert (run/'built/index.html').exists()
    assert 'changed=true' in output.read_text()
    selected=[{k:c[k] for k in ('id','period','revg','earng','gm','financialPartial','financialSignalEligible','financialRevenueComparable')} for c in D['companies'] if c['id'] in ('KBL','DZSK')]
    assert all(c['financialPartial'] and not c['financialSignalEligible'] and not c['financialRevenueComparable'] for c in selected)
    results.append(dict(force=force,exit=code,blockers=report['blockers'],htmlGenerated=True,githubOutput=output.read_text().splitlines(),
        stdout=[line for line in stream.getvalue().splitlines() if 'kb 路径' not in line],omittedUnchangedKBPathWarnings=15,partial=selected))
# Mark the screenshot-only render explicitly as local and unpublishable.
D['meta']['reviewPreview']=True;D['meta']['blockers'].append('local_review_not_publishable')
assert 'local_review_not_publishable' in release_blockers(D)
build.render(D,OUT/'after')
summary=dict(checkedAt=dt.datetime.now(dt.UTC).isoformat(),replayAt=replay_at.isoformat(),snapshotSHA256=hashlib.sha256(raw).hexdigest(),
 sourceEvidenceSHA256=hashlib.sha256((HERE/'public-evidence.json').read_bytes()).hexdigest(),networkRequests=0,runs=results,
 companies=42,financialVerified=sum(c['provenance']['financial']['status']=='verified' for c in D['companies']),
 financialPartial=sum(c['financialPartial'] for c in D['companies']),
 original40Complete=sum(all(c[k] is not None for k in ('revg','earng','gm')) for c in D['companies'] if not c['financialPartial']),
 signalEligible=sum(c['financialSignalEligible'] for c in D['companies']),mcapAvailable=sum(c['mcapUSD'] is not None for c in D['companies']),
 sameDateFX=sum(c['provenance']['valuation']['fx']['asOf']==c['ld'] for c in D['companies']),deployed=False)
assert (summary['financialVerified'],summary['financialPartial'],summary['original40Complete'],summary['signalEligible'],summary['mcapAvailable'])==(40,2,37,36,42)
(HERE/'replay-receipt.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='runs'},ensure_ascii=False,indent=2))
