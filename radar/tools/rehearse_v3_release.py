"""Write a deterministic offline rehearsal, never a production-ready deployment."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'radar/scripts'))
sys.path.insert(0, str(ROOT / 'radar/tests'))
import production_collect as collector
import production_release as release
from notion_fixture_market import fixture_market
from notion_fixtures import FixtureSet, FakeTransport


def rehearse(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('rehearsal_destination_exists')
    env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': collector.REPOSITORY,
           'GITHUB_REF': 'refs/heads/' + collector.LIVE_BRANCH, 'GITHUB_EVENT_NAME': 'workflow_dispatch',
           'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_RUN_ID': '0',
           'GITHUB_SHA': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    destination.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix='notion-rehearsal-') as temporary:
        fixture = FixtureSet(Path(temporary))
        transport = FakeTransport(fixture)
        clock = dt.datetime.fromisoformat(fixture.clock)
        sentinel = 'ntn_OFFLINE_REHEARSAL_SENTINEL_ONLY'
        with patch('socket.socket', side_effect=AssertionError('Rehearsal network is forbidden')):
            collected = collector.collect(out=destination / 'bundle/receipt.json', work=destination / 'work',
                token=sentinel, transport=transport, market_collect=fixture_market,
                clock=lambda: clock, env=env, live_dry_run=True, sleep=transport.sleep, pace=transport.pace)
            manifest = release.prepare_rehearsal(destination / 'bundle', destination / 'release',
                                                 now=clock, env=env)
        if manifest.get('publicationAuthorized') is not False or manifest.get('purpose') != 'offline-rehearsal':
            raise ValueError('rehearsal_publication_boundary')
        check = subprocess.run([shutil.which('node') or 'node', 'verify-release.cjs', '--check-only'],
            cwd=destination / 'release', capture_output=True, timeout=60)
        if check.returncode:
            raise ValueError('rehearsal_verification_failed')
        for path in destination.rglob('*'):
            if path.is_file() and sentinel.encode() in path.read_bytes():
                raise ValueError('synthetic_sentinel_leak')
        shutil.copyfile(destination / 'work/step-summary.md', destination / 'step-summary.md')
        shutil.copyfile(destination / 'release/release.json', destination / 'release.json')
        receipt = {'offline': True, 'publicationAuthorized': False, 'verified': True,
                   'notionRequests': collected['data']['meta']['notion']['requests'],
                   'marketRequests': 0, 'source': 'Provided Notion fixtures and 2026-10-21 quote fixture',
                   'sourceSHA': env['GITHUB_SHA']}
        (destination / 'rehearsal.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = rehearse(args.out)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
