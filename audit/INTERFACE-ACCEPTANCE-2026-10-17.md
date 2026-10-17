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

## Single authorized run — terminal result

The parent independently approved the pre-run review. Immediately before dispatch, the remote ref still matched `c60d9f7f70b01e94b2367e02d4a46ab6ff5420ed`, the repository remained private and workflow 387767552 had zero runs. The existing Actions $0 paid-overage budget with usage blocking and included allowance were rechecked without changing settings. A local exclusive-create dispatch marker was written before exactly one POST; it returned exit 0 at 2026-10-17 16:01:03 UTC. No rerun or additional dispatch was issued.

- [Run 39047568864](https://github.com/lwd619783-byte/research-radar/actions/runs/39047568864): `completed / success`, `workflow_dispatch`, attempt 1, exact reviewed execution SHA above.
- [Job 117439284589](https://github.com/lwd619783-byte/research-radar/actions/runs/39047568864/job/117439284589): `completed / success`, 16:01:09–16:02:35 UTC, 86 seconds. Standard `ubuntu-24.04`, image `20261012.334.1`, runner `2.337.0`, Python `3.12.15`. No model/service-tier settings were changed.
- Linux preflight, before requests: 75 tests passed, 9 frozen hashes matched, 57 schema warnings and 0 errors. Probe interval: 16:01:22.856203–16:02:32.434319 UTC (2026-10-17).
- Exactly 119 GET attempts of the 240 maximum: 118 HTTP 200, one cookie-seed HTTP 404. No 401, 403, 429 or 451 was observed; no retry or access-denial lane activation occurred. That establishes this run's access only, not future reliability.

### Four distinct result layers

The last column is the receipt's **per-interface prerequisite**, not an integrated publication authorization. Connection and parse count diagnostic rows, not HTTP requests. One quote batch supplies multiple rows.

| Category | Connection | JSON parse | Data quality | Interface prerequisite |
|---|---:|---:|---:|---:|
| Yahoo company daily | 42/42 | 42/42 | 41/42 | 41/42 |
| Tencent company raw/qfq backup | 24/24 | 24/24 | 0/24 | 0/24 |
| Yahoo valuation | 42/42 | 42/42 | 40/42 | 40/42 |
| Yahoo indices | 8/8 | 8/8 | 5/8 | 5/8 |
| Tencent indices | 5/5 | 5/5 | 5/5 | 0/5 |
| Yahoo FX | 6/6 | 6/6 | 6/6 | 6/6 |
| Tencent monthly + independent daily | 2/2 | 2/2 | 2/2 | 2/2 |
| Separate Yahoo monthly fallback | 2/2 | 2/2 | 0/2 | 0/2 |

All 42 company daily and valuation observations date to 2026-10-16; Yahoo daily phase was closed for 42/42. Yahoo valuation's 40+2 batches each succeeded in one request, returned 42 records and obtained an in-memory cookie/crumb. Neither authentication material nor its hashes were persisted. All 42 market-cap fields were positive, dated and currency-matched at the interface layer; `LITE` and `000660.KS` did not satisfy positive trailing-PE checks. The receipt cannot distinguish missing from nonpositive PE, so no more specific cause is claimed.

`688825.SS` has 54 daily observations, beginning 2026-07-27, on both sources. It cannot meet the frozen two-year/history and 52-week display requirements; no synthetic history was substituted. Tencent raw series were valid for 24/24, complete adjustments for 21/24, with missing adjustments for `0522.HK`, `688825.SS` and `1888.HK`. All 24 lacked proven currency/timezone metadata and remained `phase=unknown`; the zero full-quality count must not be read as zero successful raw-price connections.

Five Yahoo indices and all five Tencent indices date to 2026-10-16. Yahoo `399006.SZ`, `000922.SS` and `HSTECH.HK` did not produce usable index results. Their final diagnostic code is `separate_source_only`: the isolated source check prevented the adapter from silently mixing in Tencent. The receipt does not preserve the preceding Yahoo semantic failure in detail, so it cannot identify a more specific root cause. Tencent's five index prices/changes passed quality, but all five fail the closed-phase prerequisite because phase is unknown.

All six FX directions and dates passed their own interface checks. EUR inversion was verified. However CNY, EUR, HKD and KRW are dated 2026-10-17, while JPY and TWD are dated 2026-10-16. Only 2/6 FX dates match the page/quote date 2026-10-16. The production assembly explicitly requires same-day FX for market-cap conversion. From the frozen currency inventory and these dates, 27/42 companies have mismatched FX dates and only 15/42 have a compatible USD/same-day FX path. These are derived coverage counts; the aggregate missing-market-cap blocker below is directly recorded. Thus the row-level FX 6/6 prerequisite is not evidence of integrated usability.

Tencent temperature-series current values are independently dated 2026-10-16 on both sides and agree with the page date. Growth has 197 monthly points / 196 completed months; dividend has 200 / 199. Both exceed 120 completed months; the production ratio is available. Each Yahoo monthly fallback returned only one monthly point, zero completed months and no proven current date; neither fallback qualifies.

### Integrated publication remains blocked

The actual production assembly recorded these exact blockers:

1. `financial_evidence_missing_or_incompatible_with_frozen_text`
2. `missing_market_cap_fixed_area_label`
3. `short_price_history_fixed_chart_labels`

Its page date is 2026-10-16 across all seven configured markets; missing/stale company daily counts are both zero. Financial verification remains 0/42 in the frozen repository inputs. The separate team's 42-item evidence matrix was not written into code or data in this phase. Missing Yahoo index results are separately visible in interface diagnostics; the aggregate blocker list is not an exhaustive inventory of all source deficiencies. No build output, cache, fingerprint or deployment was produced, and the green workflow result means only that diagnostics and receipt upload completed.

### Artifact verification and cost evidence

[Artifact 12105379877](https://github.com/lwd619783-byte/research-radar/actions/runs/39047568864/artifacts/12105379877), `radar-interface-acceptance-39047568864`, expires 2026-10-24 16:02:32 UTC. Downloaded ZIP contains exactly `receipt.json`; private repository access is unchanged.

- ZIP: 12,530 bytes; SHA-256 `2d5417d0587fc516a9bcff60dff693976c7ab985de23cc0fb6f47449cad7e6c6`, identical to GitHub's artifact digest and upload log.
- Receipt: 155,662 bytes; SHA-256 `20fb2d0966b1bd7a33ad401cd850e1ad01f505f09a8e6619bf6f94c9697327dc`, identical to the job's output hash. Execution SHA/run ID/attempt, 131 rows and all 119 request records were checked. A scoped sensitive-pattern scan found no credentials/query URLs/private local paths.
- Full receipt/ZIP were downloaded locally. They are not added to Git history; only the concise sanitized verification summary and allowlisted job-log excerpts accompany this report, preserving the hosted artifact's seven-day retention.
- Post-run billing UI showed Actions **2 of 2,000 included minutes used**, storage **0 of 0.5 GB** at displayed precision, and **$0 billable** ($0.19 usage minus $0.19 included discount). This is the observed account-level meter, not an invented line-item charge; later metering may lag. The existing $0 overage budget was not changed. Job timeout remains 20 minutes; the receipt remains below its 512 KiB cap.
- Final read-only run listing still contained exactly one run, attempt 1; repository deployment listing contained zero. Nine frozen files remained identical, and the worktree was clean before adding this result documentation. No cron, permission expansion, financial edit, frontend edit, data edit or additional execution occurred.

Remaining work is limited to the documented source/data compatibility gaps, independent financial evidence integration and separate private-publication acceptance. This run does not authorize a further dispatch or publication.
