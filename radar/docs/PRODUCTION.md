# Protected production and automatic refresh (2026-10-21)

The owner explicitly authorized current market refresh and automatic Git publication,
while retaining the current login protection. This supersedes the earlier
manual-only execution scope for the new `radar-production.yml` workflow only.
Historical acceptance workflows, disabled publication files, evidence, and frozen
frontend/data hashes are preserved. No data gate is relaxed.

## Flow

### Authorized content maintenance (2026-10-21)

The owner subsequently authorized the first three reviewed improvements and their
production release: sourced earnings-calendar dates/status, independent research
review dates and expiry, and the deep-drawdown count. The reviewed frontend/data
files may change for this scope; update their frozen hashes with old/new hashes
and scope evidence in `audit/content-fixes-2026-10-21/`. Other frozen files and all
publication, financial, market-data and authentication gates remain intact.

`next_earnings` is the sole date for a company. `{{earnings:ID}}` references in
flash/chokepoint text resolve that date and its status. Optional `earnings` metadata
uses `confirmed`, `estimated`, or `unverified`, with HTTPS source, publication
date, verification date, and timezone required for the first two. Missing evidence
stays unverified; future evidence is unavailable in historical snapshots. Past
dates stay visible for review rather than being treated as a future event.

Weekly/industry/chokepoint `review` metadata defaults to `unverified` with no
verification date. `verified` requires a source, rationale, verification date, and
valid-until date. Weekly periods and expired reviews are labeled at display time.
Market refresh must never advance these dates or change research scores. Existing
opinions and scores are retained as unverified; no new research conclusion is
admitted by this maintenance change.

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
5. Use the short-lived repository GITHUB_TOKEN only for verified-baseline reads, publishing, and result/recovery verification. Collection and rendering have no token.
   Refuse obsolete source runs; push a normal fast-forward production commit.
6. Vercel Git integration verifies hashes and serves only `public/index.html`, `public/robots.txt`, and the login-protected
   `public/version.json`. Failed collection, gates, tests, or builds retain the last
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
configuration does not change billing budgets. Runs are bounded to 30 minutes, including deployment verification and one recovery attempt.

## Operation

Use GitHub Actions → Radar refresh and publish → Run workflow on the source branch
for an extra update; do not use Re-run because source receipts bind attempt 1.
Failure details are in the run logs. Successful source/clock/data/file hashes are
recorded in `production:release.json` and the seven-day private workflow artifact.
To pause, disable only `radar-production.yml`; the last site remains available.
To revert a release, promote the desired known-good Vercel deployment; pause the
workflow first if it should not be replaced by the next scheduled snapshot.


## Authorized operations and evidence improvements (2026-10-21)

The owner explicitly authorized the remaining three reviewed improvements and
production release: deployment result/failure visibility, clickable data sources,
and daily factual changes. Frontend hashes may change for these features; scope
and old/new hashes are recorded in `audit/operations-2026-10-21/`. Data configuration,
research values, authentication, financial admission, collection budgets and all
historical evidence remain protected.

The workflow now reads the most recent production commit with a successful Vercel
status for this exact project (bounded to 12 commits), verifies its manifest and
embedded DATA digest, and uses it as the baseline. A normal fast-forward publish
is followed by polling the exact production SHA's Vercel commit status for at
most five minutes. Pending, another project's status, failure, API error or timeout
cannot be reported as success. Anonymous requests to `/` and `/version.json` must
still encounter login protection. The authenticated browser checks same-origin
version metadata every two minutes while visible, including the actual build's
`VERCEL_GIT_COMMIT_SHA`, and offers an explicit refresh when new data arrives.
This browser check verifies the served domain content; the workflow itself does
not read through SSO and does not claim that an anonymous 302 proves page content.

On failure, the workflow records the failed stage and attempts one ordinary Git
publication of the previously verified static release with only its operations
notice changed. DATA, research flags, daily changes and its original timestamp
remain identical. Recovery itself is checked for at most three minutes; the run
still fails. No loop or automatic force push is allowed. If the hosting service or
Git itself is unavailable, the notice cannot be published; the old page then shows
an overdue-update warning (one-hour allowance beyond the configured schedule),
and the private Actions run retains failure annotations and diagnostics for seven
days via an `always()` upload. This is an in-app/Actions failure indication, not a
new email or external messaging subscription. Schedules are not exchange holiday
calendars; warnings describe update timeliness without guessing market failures.

`history.json` is private release metadata, outside `public/`, hashed in the release
manifest. It retains at most eight days, each with the last verified snapshot for
that date. Daily changes prefer the latest earlier day; on the first day they say
"compared with the previous successful update". A missing baseline stays unknown.
Same-day prices, source/currency/return-basis changes and missing data are excluded.
New daily observations use the existing admitted one-day adjusted return; they
never divide displayed intraday prices or raw closes to manufacture a return.
Financial period and evidence changes are factual notices, not cross-period growth
calculations. Unverified calendar changes and research opinions retain their labels.

Financial evidence uses existing original URLs, disclosure/verification dates,
accounting and calculation notes. Supplier market/history links are explicitly
current reference pages, not archived proof. Invalid links, unavailable research
notes, missing companies and missing data remain visibly missing or pending.
