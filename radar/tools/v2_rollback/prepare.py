"""Prepare a tested V2 rollback commit locally; never push, deploy or fetch."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PATCH_SHA256 = '4b31a751f5363215a958e6410986649fe9d31f24ecfb1ab0edcc50e1e358f608'
PIN_SLOT = "ROLLBACK_BASELINE_SHA = 'a24e805552d8e1ce606d214a14bc08db93af50d6'"
ALLOWED_V2_CHANGES = {'radar/scripts/release_operations.py', 'radar/tests/test_rollback_v2_compatibility.py'}
ORIGINS = {'https://github.com/lwd619783-byte/research-radar',
           'git@github.com:lwd619783-byte/research-radar',
           'ssh://git@github.com/lwd619783-byte/research-radar'}
TEST_SCRIPT = r'''
import json,pathlib,sys,unittest
root=pathlib.Path.cwd()
sys.path[:0]=[str(root/'radar/scripts'),str(root/'radar/tests')]
suite=unittest.defaultTestLoader.loadTestsFromNames(['test_rollback_v2_compatibility','test_release_operations','test_production_release'])
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'testsRun':result.testsRun,'passed':result.wasSuccessful()}))
raise SystemExit(not result.wasSuccessful())
'''


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--merge', required=True)
    parser.add_argument('--expected-v2-head', required=True)
    parser.add_argument('--expected-pr4-head', required=True)
    parser.add_argument('--rollback-baseline-sha', required=True,
                        help='Recorded healthy V2 production commit; checked again by the workflow')
    parser.add_argument('--patch', type=Path,
                        default=Path(__file__).with_name('v2-rollback-compatibility.patch'))
    return parser.parse_args(argv)


def git(repo, *arguments):
    return subprocess.check_output(['git', *arguments], cwd=repo, text=True,
                                   encoding='utf-8', stderr=subprocess.STDOUT).strip()


def prepare(args):
    repo = args.repo.resolve()
    for value in (args.merge, args.expected_v2_head, args.expected_pr4_head, args.rollback_baseline_sha):
        if not re.fullmatch('[0-9a-f]{40}', value):
            raise ValueError('All commit IDs must be full 40-character hashes')
    patch_bytes = args.patch.resolve().read_bytes()
    if hashlib.sha256(patch_bytes).hexdigest() != PATCH_SHA256:
        raise ValueError('Rollback package hash mismatch; no Git changes made')
    if Path(git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
        raise ValueError('Use the repository root, not a nested directory')
    origin = git(repo, 'remote', 'get-url', 'origin').rstrip('/').removesuffix('.git').lower()
    if origin not in ORIGINS:
        raise ValueError('Origin is not the authorized research-radar repository')
    if git(repo, 'status', '--porcelain'):
        raise ValueError('Refusing dirty checkout; preserve existing changes first')
    if git(repo, 'rev-parse', 'HEAD') != args.merge:
        raise ValueError('HEAD is not the recorded PR4 merge; adapt and rehearse instead')
    if git(repo, 'show', '-s', '--format=%P', args.merge).split() != [args.expected_v2_head, args.expected_pr4_head]:
        raise ValueError('Merge parent binding mismatch')
    git(repo, 'merge-base', '--is-ancestor', args.rollback_baseline_sha, 'origin/production')
    pinned = json.loads(git(repo, 'show', args.rollback_baseline_sha + ':release.json'))
    if pinned.get('schemaVersion') != 2 or pinned.get('blockers') != []:
        raise ValueError('Pinned baseline is not a successful V2 manifest')

    # Revert removes this package from the checkout. Preserve only the verified
    # patch outside it first; no credential or repository content is copied.
    with tempfile.TemporaryDirectory(prefix='radar-v2-rollback-') as temporary:
        patch_path = Path(temporary) / 'verified-rollback.patch'
        patch_path.write_bytes(patch_bytes)
        git(repo, 'revert', '--no-commit', '-m', '1', args.merge)
        git(repo, 'apply', '--check', str(patch_path))
        git(repo, 'apply', str(patch_path))
        operations = repo / 'radar/scripts/release_operations.py'
        source = operations.read_text(encoding='utf-8')
        if source.count(PIN_SLOT) != 1:
            raise ValueError('Rollback baseline pin slot mismatch; inspect uncommitted changes')
        operations.write_text(source.replace(PIN_SLOT, f"ROLLBACK_BASELINE_SHA = '{args.rollback_baseline_sha}'"),
                              encoding='utf-8', newline='\n')
        git(repo, 'add', '--', *sorted(ALLOWED_V2_CHANGES))
        changed = set(git(repo, 'diff', '--cached', '--name-only', args.expected_v2_head).splitlines())
        if changed != ALLOWED_V2_CHANGES:
            raise ValueError('Unexpected V2 differences; inspect uncommitted changes')
        tested = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', TEST_SCRIPT],
                                cwd=repo, check=True, capture_output=True, text=True, encoding='utf-8')
        sys.stderr.write(tested.stderr)
        result = json.loads(tested.stdout.strip())
        if result.get('passed') is not True or result.get('testsRun', 0) < 6:
            raise ValueError('Rollback regression suite did not pass')
        git(repo, 'commit', '-m', 'Rollback PR4 to V2 with strict baseline compatibility')
    return {'preparedLocalCommit': git(repo, 'rev-parse', 'HEAD'), 'mergeReverted': args.merge,
            'pushed': False, 'deployed': False, 'testsPassed': result['testsRun'],
            'rollbackBaselineSHA': args.rollback_baseline_sha,
            'next': 'Review current release gates and the local commit. This tool never pushes.'}


def main(argv=None):
    try:
        print(json.dumps(prepare(parse_args(argv))))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            # Do not dump arbitrary Git output or repository-config values.
            print('Rollback command or tests failed; no push occurred. Inspect local changes.', file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
