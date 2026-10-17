# Manual interface acceptance — pre-dispatch review, 2026-10-17

Baseline: `c29cb892cb10aa3cde9f5bc7c72fdaee9d55dcd1`; private repository `lwd619783-byte/research-radar`; branch `fix/radar-data-integrity`. This phase adds a manual diagnostic workflow only. The original two `.yml.disabled` workflows, all three frontend files and four research TOMLs remain byte-identical. Production scripts and release gates are unchanged. No deployment, PR, merge, cron, dependency upgrade, access change or default-branch change is included.

## Execution and cost boundary

- Only `workflow_dispatch`; one standard `ubuntu-24.04` job, Python 3.12, 20-minute job timeout, 16-minute probe-step timeout, 14-minute internal request deadline. The reviewed SHA must equal the execution SHA, paid-overage verification must be explicitly true, and run attempts other than 1 are skipped. Exactly one dispatch is authorized for this phase; an ambiguous response must be reconciled by read-only run lookup, never a second dispatch.
- Permissions are `contents: read`; checkout persists no credentials. Three official actions are pinned to full commit SHAs, resolved from their official repositories. The only artifact path is the sanitized receipt, capped at 512 KiB, retained for seven days with the existing private repository access boundary.
- The repository's collaborator listing contained only its owner. The existing authenticated GitHub billing UI showed GitHub Free, Actions 0 of 2,000 included minutes used and 0 of 0.5 GB storage used. The existing account Actions budget showed `$0.00 / $0.00 spent`, `Usage blocked`; rechecked at approximately 15:51 UTC. No billing or budget settings were changed. A 20-minute standard Linux job and this receipt fit the observed included allowance. Final metering may lag; these are observed pre-run limits, not a fabricated final bill.
- The read-only billing REST attempt returned 404 and requested a broader user scope. No scope refresh was performed; the authorized existing browser session supplied the relevant billing evidence instead.

## Coverage and data handling

The configuration-derived inventory is 42 Yahoo company daily records; 24 Tencent company backups (22 A-share and 2 Hong Kong, raw plus qfq); 42 Yahoo valuation records in 40+2 batches with one in-memory cookie/crumb session; 8 Yahoo indices plus 5 configured Tencent backups; 6 FX directions/dates; and 2 Tencent monthly-plus-independent-daily temperature series plus 2 separately exercised Yahoo monthly fallbacks. These form 131 diagnostic rows and at most 119 planned GETs before bounded retries.

Every row distinguishes HTTP connection, JSON parse, data quality and its interface-level publication prerequisite. Top-level `publication.blockers` separately contains the actual production release gate results from an in-memory primary-source assembly; an individual row's `publicationGate=true` does not authorize publishing the dashboard. Tencent unknown phase remains unknown and fails the close prerequisite. Monthly bucket timestamps remain insufficient evidence of the current observation day. HTTP 200 with empty data can pass connection/JSON parsing and still fail quality.

Only three HTTPS hosts and specific endpoint classes are allowed; redirects and alternate Yahoo identity/host fallbacks are blocked. There is a global limit of 240 GETs, eight seconds per request and one retry only for HTTP 429 with a numeric delay at most ten seconds. Longer or HTTP-date retry instructions are not shortened or retried. HTTP 401/403/451 closes its corresponding lane. Subsequent rows still record unavailable status; no credentials, proxy, firewall or network restrictions are changed.

Raw response bytes/JSON, cookies, crumb, full query URLs, headers, private research text and exception messages remain in memory only. The receipt retains approved timestamps/counts/quality booleans, endpoint host/class/status, response hashes/byte counts and release-blocker codes. Runner image/version, Python, OS/kernel, run ID/attempt and execution SHA are recorded. It writes no production DATA, build report, rendered site, cache or fingerprint. The original 57 schema evidence/path warnings and 42-company financial-evidence gap remain; no financial evidence is invented.

## Offline evidence

See `acceptance-2026-10-17/` for commands, UTC start/end times, child exit codes and logs. The starting 55 tests passed. The final suite has 75 passing tests: the existing 55 plus 20 transport/quality/redaction/inventory/workflow tests. The old no-active-workflows assertion was narrowed only to the explicitly authorized manual workflow. Final preflight returns 75 tests, 9 frozen files, 57 schema warnings, 0 schema errors, exit 0.

The first preparation attempt had a local quoting error and omitted the frozen manifest; preflight failed with `FileNotFoundError`, exit 2, before any external request. The corrected final preflight passed. Intermediate 73-test output is retained but is not presented as the final count. The scoped secret-pattern scan found no credentials; its one credential-shaped URL is the explicit synthetic rejection fixture `user:secret` in a test. The full failed-source collection test confirms all 131 planned rows and financial blockers survive sanitized exceptions. No local live market API requests were made.

## Pending run/result

The execution commit, remote SHA, single run ID, terminal status, artifact digest, receipt byte hash, component results and post-run unchanged-file checks will be appended after the authorized run. Workflow success means the diagnostic completed; it never means all interfaces or release prerequisites passed. Any failure remains a gap and does not authorize rerun.

The disabled cron's weekday range and any future `0-5` proposal remain separate review work. This acceptance provides no promise of three daily publications. Real financial evidence and private publication/access acceptance remain separate prerequisites.
