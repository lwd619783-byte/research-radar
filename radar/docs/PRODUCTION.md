# Protected production and automatic refresh (2026-10-21)

The owner explicitly authorized current market refresh and automatic Git publication,
while retaining the current login protection. This supersedes the earlier
manual-only execution scope for the new `radar-production.yml` workflow only.
Historical acceptance workflows, disabled publication files, evidence, and frozen
frontend/data hashes are preserved. No data gate is relaxed.

## Flow

Source/default branch: `fix/radar-truthfulness-2026-10-18`.
Release branch: `production` (generated static output only; do not edit manually).
Target: Vercel team `lkdmkl`, project `research-radar`, production environment.
Vercel Authentication must remain enabled for **All Deployments**.

Pushes affecting radar code/configuration, manual dispatch, and scheduled runs:
1. Check exact source SHA; run all offline tests and frozen-file/schema checks.
2. Use the existing bounded collector (240 requests maximum, 14-minute deadline;
   explicit access denials stop that source lane; no stored cookies or credentials).
3. Verify the exact same-run archive, all publication blockers, non-synthetic data,
   and snapshot age of at most 30 minutes.
4. Render the approved frontend with a production status sentence; keep embedded
   DATA byte-equivalent as an object. No raw HTTP bodies are published.
5. Use the short-lived repository GITHUB_TOKEN only in the final publishing step.
   Refuse obsolete source runs; push a normal fast-forward production commit.
6. Vercel Git integration verifies hashes and serves only `public/index.html` and
   `public/robots.txt`. Failed collection, gates, tests, or builds retain the last
   successful production deployment.

## Schedule (Asia/Shanghai)

- Tuesday–Saturday 07:15: after the prior US trading session, including Friday.
- Monday–Friday 12:15 and 16:35: Asian market midday and after-close observations.

GitHub scheduled execution can be delayed. Holidays use the existing dated
observation policy; a missing or stale critical observation blocks publication.
Refresh updates market observations, not manually sourced financial reports,
industry scores, weekly commentary, or research judgments. Each metric retains
its own source date and missing/partial/not-applicable status.

No Vercel token, deployment bypass, new paid service, or extra account is required.
GitHub Actions usage consumes the account's existing Actions allowance; this
configuration does not change billing budgets. Runs are bounded to 20 minutes.

## Operation

Use GitHub Actions → Radar refresh and publish → Run workflow on the source branch
for an extra update; do not use Re-run because source receipts bind attempt 1.
Failure details are in the run logs. Successful source/clock/data/file hashes are
recorded in `production:release.json` and the seven-day private workflow artifact.
To pause, disable only `radar-production.yml`; the last site remains available.
To revert a release, promote the desired known-good Vercel deployment; pause the
workflow first if it should not be replaced by the next scheduled snapshot.
