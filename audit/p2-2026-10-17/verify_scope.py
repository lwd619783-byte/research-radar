"""Read-only baseline/current file hashes and scoped secret-pattern check."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(r'C:\Users\10750\Documents\Codex\2026-10-17\task\radar-local-audit')
BASE = '9ca62dc5b2c185158a8c5f28a5fb845899cea4e4'
def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)
def sha(data):
    return hashlib.sha256(data).hexdigest()
paths = git('ls-tree', '-r', '--name-only', BASE, '--', 'radar/site', 'radar/data', '.github/workflows').decode().splitlines()
frozen = {p: {'baseline': sha(git('show', BASE+':'+p)), 'after': sha((ROOT/p).read_bytes())} for p in paths}
patterns = {
    'private_key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'github_token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'aws_access': rb'AKIA[0-9A-Z]{16}',
    'credential_url': rb'https?://[^\s/:]+:[^\s/@]+@',
    'literal_secret': rb'''(?i)(?:api[_-]?key|password|secret|token)\s*[:=]\s*['"][^'"\s]{12,}''',
}
objects = git('rev-list', '--objects', '--all').decode().splitlines()
findings, blobs, binary = [], 0, 0
for entry in objects:
    oid = entry.split(' ', 1)[0]
    if git('cat-file', '-t', oid).strip() != b'blob': continue
    blob = git('cat-file', '-p', oid)
    blobs += 1
    try: blob.decode('utf-8')
    except UnicodeDecodeError: binary += 1
    for name, pattern in patterns.items():
        if re.search(pattern, blob): findings.append({'scope': 'history', 'object': oid, 'rule': name})
changed = git('diff', '--name-only', BASE).decode().splitlines()
changed += git('ls-files', '--others', '--exclude-standard').decode().splitlines()
for p in changed:
    blob = (ROOT/p).read_bytes()
    for name, pattern in patterns.items():
        if re.search(pattern, blob): findings.append({'scope': 'working', 'path': p, 'rule': name})
result = {'baseline': BASE, 'head': git('rev-parse', 'HEAD').decode().strip(), 'frozen': frozen,
          'allFrozenEqual': all(v['baseline'] == v['after'] for v in frozen.values()),
          'historyBlobsScanned': blobs, 'binaryBlobs': binary, 'workingFilesScanned': changed,
          'patterns': list(patterns), 'findings': findings,
          'scopeNote': 'Finite pattern scan; no credentials/config/other sessions read. Binary files unchanged.'}
print(json.dumps(result, indent=2))
assert result['allFrozenEqual'] and not findings
