"""Replay this session's real market snapshot through main; never publish."""
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'radar/scripts'))
import build
HERE=Path(__file__).resolve().parent
snapshot=Path('/tmp/radar-live-market.json')
market=json.loads(snapshot.read_text())
results=[]
for offline,expected in [(False,3),(True,2)]:
    with tempfile.TemporaryDirectory(prefix='radar-gate-') as directory:
        base=Path(directory);out=base/'out';output=base/'output.txt';audit=base/'audit.json'
        args=['build.py','--force','--cache',str(base/'cache.json'),'--out',str(out),'--audit-json',str(audit)]
        if offline:args.append('--offline')
        stream=io.StringIO()
        with patch.object(sys,'argv',args),patch.dict(os.environ,{'GITHUB_OUTPUT':str(output),'GITHUB_STEP_SUMMARY':str(base/'summary.md')}),contextlib.redirect_stdout(stream):
            if offline:
                code=build.main()
            else:
                with patch.object(build,'fetch_all',return_value=(market,['Replay of real session snapshot; no new network request'])):
                    code=build.main()
        report=json.loads(audit.read_text())
        assert code==expected,(code,stream.getvalue())
        assert not out.exists()
        assert output.read_text().strip()=='changed=false'
        if not offline:assert report['blockers']==['financial_evidence_incomplete']
        results.append(dict(mode='empty-offline-force' if offline else 'real-snapshot-replay-force',exit=code,
                            blockers=report['blockers'],rendered=False,githubOutput=output.read_text().strip(),stdout=stream.getvalue()))
receipt=dict(checkedAt=dt.datetime.now(dt.UTC).isoformat(),snapshotSHA256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),results=results)
(HERE/'release-gate-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({**receipt,'results':[{k:v for k,v in r.items() if k!='stdout'} for r in results]},ensure_ascii=False,indent=2))
