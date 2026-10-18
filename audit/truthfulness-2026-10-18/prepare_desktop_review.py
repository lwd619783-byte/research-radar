"""Recreate the exact baseline under /tmp and render both real-data review pages."""
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
BASE='414eb80626d3200dfebe4a010507c5fe74d7ca31'
OUT=Path('/tmp/radar-desktop-review')
CHECKOUT=Path('/tmp/radar-baseline-review')
files=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'radar/scripts','radar/data','radar/site'],cwd=ROOT,text=True).splitlines()
for name in files:
    p=CHECKOUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT))
code='''import json,datetime as dt,sys
from pathlib import Path
sys.path.insert(0,'/tmp/radar-baseline-review/radar/scripts')
import build
mk=json.loads(Path('/tmp/radar-live-market.json').read_text())
now=dt.datetime.now(build.BJ)
data,rep=build.load_and_validate(build.RADAR,build.REPO,now.date())
D,_,_=build.assemble(data,mk,mk,now)
D['meta']['reviewPreview']=True
build.render(D,Path('/tmp/radar-desktop-review/before'))
'''
subprocess.run([sys.executable,'-c',code],check=True)
subprocess.run([sys.executable,str(Path(__file__).with_name('assemble_review.py'))],cwd=ROOT,check=True)
print('Local before/after pages use the same actually fetched market snapshot; baseline files are exact Git blobs. No deployment/cache.')
