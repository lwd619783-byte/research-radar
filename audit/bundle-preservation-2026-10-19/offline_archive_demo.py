"""OFFLINE TEST DATA ONLY: archive the existing synthetic/old-sample fixture.

This does not reconstruct any Actions run or fetch new market data. The execution
SHA identifies this local code checkout; run ID 0 is an explicit offline sentinel.
"""
import datetime as dt
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'radar/scripts'))
import acceptance_bundle as bundle
import build


def main():
    D = json.loads((ROOT / 'audit/offline-page-acceptance-2026-10-19/test-data.json').read_text())
    clock = dt.datetime.fromisoformat(D['meta']['generatedAt'])
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    receipt = {
        'schemaVersion': 1, 'purpose': 'OFFLINE TEST — NOT A REAL ACTIONS RUN OR NEW MARKET DATA',
        'execution': {'GITHUB_SHA': sha, 'GITHUB_RUN_ID': '0', 'GITHUB_RUN_ATTEMPT': '1'},
        'fixedClock': clock.isoformat(), 'requestsMade': 0,
        'sampleSource': 'audit/offline-page-acceptance-2026-10-19/test-data.json',
        'publication': {'dataSHA256': bundle.data_digest(D), 'asOf': D['meta']['asOf'],
                        'snapshot': D['meta']['snapshot'], 'blockers': build.release_blockers(D)},
    }
    with tempfile.TemporaryDirectory(prefix='radar-OFFLINE-TEST-ONLY-') as tmp, patch.object(socket.socket, 'connect', side_effect=AssertionError('offline example attempted a socket')) as network:
        target = Path(tmp) / 'OFFLINE-TEST-ONLY'
        saved = bundle.write_bundle(target, D, receipt, clock)
        assert saved == bundle.verify_bundle(target)
        network.assert_not_called()
    result = {'classification': 'OFFLINE TEST ONLY — NOT NEW REAL MARKET DATA',
              'checkedAtUTC': dt.datetime.now(dt.UTC).isoformat(), 'codeSHA': sha,
              'networkConnections': 0, 'newMarketRequests': 0, 'sameData': True,
              'rerenderExact': True, 'temporaryArchiveRemovedAfterVerification': not target.exists(),
              'archive': saved}
    (HERE / 'offline-demo-receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
