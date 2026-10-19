"""Reuse the prior labeled fixture, replacing only its inline production app.js."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE = '2de3aca8d5f9088fb8d7e3f57d65e0aa092f729f'
data_path = 'audit/offline-page-acceptance-2026-10-19/test-data.json'
before = (ROOT / 'audit/offline-page-acceptance-2026-10-19/preview.html').read_text()
old = subprocess.check_output(['git', 'show', BASE + ':radar/site/app.js'], cwd=ROOT, text=True)
new = (ROOT / 'radar/site/app.js').read_text()
assert before.count(old) == 1
after = before.replace(old, new, 1)
for name, html in [('before', before), ('after', after)]:
    (HERE / (name + '.html')).write_text(html)
receipt = {
    'baseSHA': BASE,
    'dataPath': data_path,
    'dataSHA256': hashlib.sha256((ROOT / data_path).read_bytes()).hexdigest(),
    'dataChanged': False,
    'classification': 'Same explicitly synthetic/old-sample component fixture; NOT original Actions DATA',
    'beforeHTMLSHA256': hashlib.sha256(before.encode()).hexdigest(),
    'afterHTMLSHA256': hashlib.sha256(after.encode()).hexdigest(),
}
(HERE / 'fixture-reuse.json').write_text(json.dumps(receipt, indent=2) + '\n')
