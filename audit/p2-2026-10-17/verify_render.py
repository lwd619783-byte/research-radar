"""Compare baseline/fixed renderer on the exact same synthetic assembled DATA."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType

ROOT = Path(r'C:\Users\10750\Documents\Codex\2026-10-17\task\radar-local-audit')
sys.path.insert(0, str(ROOT/'radar/tests'))
from test_review_regressions import build, complete_dataset, NOW
source = subprocess.check_output(['git', 'show', '9ca62dc5b2c185158a8c5f28a5fb845899cea4e4:radar/scripts/build.py'], cwd=ROOT)
baseline = ModuleType('baseline_renderer')
baseline.__file__ = str(ROOT/'radar/scripts/build.py')
exec(compile(source, baseline.__file__, 'exec'), baseline.__dict__)
data, mk = complete_dataset()
D = build.assemble(data, mk, mk, NOW)[0]
D['meta']['fixture'] = 'SYNTHETIC render comparison, never publish'
with tempfile.TemporaryDirectory() as td:
    before = baseline.render(D, Path(td)/'before')
    after = build.render(D, Path(td)/'after')
    assert before.read_bytes() == after.read_bytes()
    print(json.dumps({'sameDataHtmlByteIdentical': True, 'sha256': hashlib.sha256(after.read_bytes()).hexdigest(),
                      'bytes': after.stat().st_size, 'companies': len(D['companies']), 'synthetic': True}))
