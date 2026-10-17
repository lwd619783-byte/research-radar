"""LOCAL ONLY: synthetic market fixture for frozen-template visual comparisons.

Never deploy its output. Research strings are the unchanged handoff content.
"""
import datetime as dt
import hashlib
import json
import subprocess
import types
from pathlib import Path
import build

baseline = types.ModuleType('radar_baseline')
baseline.__file__ = build.__file__
exec(compile(subprocess.check_output(['git', 'show', '22d9601:radar/scripts/build.py'], cwd=build.REPO).decode('utf-8'),
             '<verified-baseline-build>', 'exec'), baseline.__dict__)

ROOT = build.REPO
OUT = ROOT / 'audit' / 'visual'
OUT.mkdir(parents=True, exist_ok=True)
now = dt.datetime(2026, 10, 17, 12, tzinfo=build.BJ)
data, report = build.load_and_validate(build.RADAR, ROOT, now.date())
assert not report.errors
mk = {k: {} for k in ('daily', 'quote', 'index', 'fx', 'ratio')}
start = dt.date(2024, 10, 1)
dates = [start + dt.timedelta(days=i) for i in range(746)]
dates = [d for d in dates if d.weekday() < 5]
for i, c in enumerate(data['companies']):
    bars = [[d.isoformat(), round(50 + i + j * .03 + (j % 19) * .3, 3),
             round(50 + i + j * .03 + (j % 19) * .3, 3)] for j, d in enumerate(dates)]
    mk['daily'][c['sym']] = {'bars': bars, 'src': 'synthetic-test-only', 'currency': c['cur']}
for i, x in enumerate(data['config']['indices']):
    mk['index'][x['symbol']] = {'price': 3000 + i * 100, 'chg': .01, 'date': dates[-1].isoformat()}
months = [f'{2015 + i // 12:04}-{i % 12 + 1:02}' for i in range(130)]
mk['ratio'] = {'cyb': [[m, 1200 + (i % 17) * 20] for i, m in enumerate(months)],
               'hl': [[m, 3000] for m in months]}
D, _, _ = baseline.assemble(data, mk, mk, now)
D['meta']['fixture'] = 'SYNTHETIC: visual regression only, never publish'
(OUT / 'fixed-data.json').write_text(json.dumps(D, ensure_ascii=False), encoding='utf-8')
baseline.render(D, OUT / 'before')
build.render(D, OUT / 'after')
assert (OUT/'before/index.html').read_bytes() == (OUT/'after/index.html').read_bytes()
hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((build.RADAR / 'site').iterdir())}
expected = json.loads((ROOT/'audit/frontend-baseline.json').read_text(encoding='utf-8'))
assert hashes == expected
(ROOT / 'audit' / 'frontend-verification.json').write_text(json.dumps({
    'unchanged': hashes == expected, 'hashes': hashes, 'sameDataHtmlByteIdentical': True,
    'htmlSha256': hashlib.sha256((OUT/'after/index.html').read_bytes()).hexdigest(),
    'fixture': 'synthetic prices; original unverified research strings; not for deployment'
}, indent=2), encoding='utf-8')
print(json.dumps({'counts': [len(data[k]) for k in ('industries', 'chokepoints', 'companies')],
                  'frontend': hashes, 'visual': str(OUT)}, ensure_ascii=False, indent=2))
