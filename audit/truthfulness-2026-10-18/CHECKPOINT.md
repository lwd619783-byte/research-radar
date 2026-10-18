# 2026-10-18 local repair checkpoint

Authorized: gpt-6-astra / high / Standard. This runtime exposes no model/reasoning/service-tier receipt; actual acceptance configuration is unverified. No setting was changed.

Repository read-only API returned `lwd619783-byte/research-radar`, private=true, default_branch=`fix/radar-data-integrity`. Fetch and remote HEAD lookup at 02:06:14 UTC both confirmed `414eb80626d3200dfebe4a010507c5fe74d7ca31`; initial local `work` was clean. New branch: `fix/radar-truthfulness-2026-10-18`. No AGENTS.md was found under /workspace or at its ancestors. HANDOFF.md and INTERFACE-ACCEPTANCE-2026-10-17.md were read. The user's current instructions supersede historical main/deployment guidance.

Initial ordinary urllib probes: GitHub API 200 at 02:06:12 UTC, Yahoo AAPL 429 at 02:06:14, Frankfurter historical FX 403 at 02:06:14. Frankfurter was stopped. The repository's existing client subsequently obtained Yahoo CXMT daily history at 02:08:22 UTC: 200, 6758 bytes, 54 bars, SHA256 3f378842978d313116a93804594fbddca8e0d9b315a068f9fe457bc5eb6308bc. No alternate Yahoo host, proxy, credential or security-setting change was used. Initial CNINFO/NVIDIA public source GETs returned 200 at 02:08:30/31 UTC. These are access observations, not complete content acceptance.

Baseline: 75 tests freshly run, passed (baseline-tests.txt). Core repair: 88 tests freshly run, passed (core-tests.txt); `node --check radar/site/app.js` passed. CSS and HTML template remain byte-identical. Financial TOML is not changed in this checkpoint; the financial candidate package is reviewed separately. Old test logs are historical, not this run's evidence.

Core: dated historical FX selection; separate quote/financial currency; explicit PE status; independent index semantic diagnostics; richer financial provenance and eligibility; truthful short-history/financial/placeholder-area labels. Missing financial evidence, uncertain closes, mixed/stale market dates and offline/fixture output remain publication blockers. Missing cap and short history are now explicitly representable instead of a false fixed label. The new scope manifest is audit/truthfulness-frozen.json; historical manifests are retained unchanged.

No Actions dispatch, cron activation, workflow edit, merge, deployment, permission change, force push or main creation. Raw downloaded public documents and temporary market snapshot are outside Git. Candidate/source receipts and desktop acceptance are not claimed complete here.
