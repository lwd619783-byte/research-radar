"""Capture this revision's commands and exit codes without inheriting old receipts."""
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(r'C:\Users\10750\Documents\Codex\2026-10-17\task\radar-local-audit')
OUT = Path(__file__).parent/'checks'
OUT.mkdir(exist_ok=True)
label, *command = sys.argv[1:]
start = dt.datetime.now(dt.UTC).isoformat()
p = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
output = p.stdout.decode('utf-8', 'replace')
match = re.search(r'Ran (\d+) tests? in', output)
meta = dict(command=command, cwd=str(ROOT), startedAt=start,
            finishedAt=dt.datetime.now(dt.UTC).isoformat(), exitCode=p.returncode,
            tests=int(match[1]) if match else None)
(OUT/(label+'.txt')).write_text(output, encoding='utf-8')
(OUT/(label+'.json')).write_text(json.dumps(meta, indent=2), encoding='utf-8')
print(json.dumps(meta))
print(output[-10000:])
sys.exit(p.returncode)
