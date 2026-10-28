"""Export bounded collection failure codes; never copy a Notion handoff or text."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

import acceptance_bundle as bundle
import production_collect as collector
from research_snapshot import canonical_json

FILES = ('diagnostic.json', 'step-summary.md')
MAX_ARTIFACT = 32768


def export(work, destination):
    if 'NOTION_TOKEN' in os.environ:
        raise ValueError('unexpected_secret_scope')
    destination = Path(destination)
    if destination.exists() or any(part.is_symlink() for part in (destination, *destination.parents)):
        raise ValueError('diagnostic_destination_exists')
    diagnostic = collector.read_diagnostic(Path(work) / 'diagnostic.json')
    lines = ['### 投研雷达 · 安全采集诊断', '- 本次采集失败，未授权发布。',
             '- code: ' + diagnostic['code']]
    if 'stage' in diagnostic:
        lines.append('- stage: ' + diagnostic['stage'])
    if diagnostic.get('blockers'):
        lines.append('- blockers: ' + ', '.join(diagnostic['blockers']))
    payload = {'diagnostic.json': canonical_json(diagnostic).encode('utf-8'),
               'step-summary.md': ('\n'.join(lines) + '\n').encode('utf-8')}
    for value in payload.values():
        bundle.check_sensitive(value.decode('utf-8'))
    if set(payload) != set(FILES) or sum(map(len, payload.values())) > MAX_ARTIFACT:
        raise ValueError('diagnostic_size_limit')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.collection-diagnostic-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'artifact'; stage.mkdir()
        for name, content in payload.items():
            (stage / name).write_bytes(content)
        bundle.atomic_directory_rename(stage, destination)
    return {'exported': True, 'files': list(FILES), 'publicationAuthorized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = export(args.work, args.out)
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({'exported': False, 'code': 'diagnostic_export_failed', 'publicationAuthorized': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
