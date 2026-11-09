"""Exact workflow identity for additional read-only rehearsal branches."""

REPOSITORY = 'lwd619783-byte/research-radar'
SOURCE_BRANCH = 'fix/radar-truthfulness-2026-10-18'
LEGACY_LIVE_BRANCH = 'v3/pr4-production'
PREPARATION_BRANCH = 'v3/pr5-stable-operations'
LIVE_WORKFLOW = '.github/workflows/radar-interface-acceptance.yml'


def dry_run_ref_allowed(env):
    ref = env.get('GITHUB_REF')
    if ref == 'refs/heads/' + LEGACY_LIVE_BRANCH:
        return True
    if ref not in ('refs/heads/' + SOURCE_BRANCH, 'refs/heads/' + PREPARATION_BRANCH):
        return False
    return (env.get('GITHUB_WORKFLOW_REF') == REPOSITORY + '/' + LIVE_WORKFLOW + '@' + ref
            and env.get('GITHUB_WORKFLOW_SHA') == env.get('GITHUB_SHA'))
