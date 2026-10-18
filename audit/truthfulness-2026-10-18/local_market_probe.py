"""Authorized local diagnostics only; no Actions, build, cache or publishing."""
import datetime as dt
import json
from pathlib import Path
import platform
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'radar/scripts'))
import acceptance_probe as probe
import build
HERE=Path(__file__).resolve().parent
start=probe.utc()
data,report=build.load_and_validate(build.RADAR,ROOT,dt.datetime.now(build.BJ).date())
assert not report.errors,report.errors
budget=probe.Budget()
market={}
rows,summary,session,gates=probe.collect(data,budget,market)
receipt=dict(purpose='local-interface-diagnostics-not-publication',startedAt=start,finishedAt=probe.utc(),
             python=platform.python_version(),executionSHA=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             workingTree='uncommitted approved repairs; final code committed after verification',
             results=rows,summary=summary,quoteSession=session,publication=gates,
             requestsMade=budget.count,deniedPaths=sorted(budget.denied))
(HERE/'local-market-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
Path('/tmp/radar-live-market.json').write_text(json.dumps(market,ensure_ascii=False,allow_nan=False))
print(json.dumps({'summary':summary,'publication':gates,'requestsMade':budget.count},ensure_ascii=False,indent=2))
