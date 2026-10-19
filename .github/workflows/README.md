# Manual acceptance only; publication workflows remain disabled

The original `radar-deploy.yml.disabled` and `radar-preview.yml.disabled`
remain byte-for-byte unchanged and are not recognized as active workflows.
Their push, pull-request, schedule and deployment behavior remains disabled.

On 2026-10-17 the user explicitly authorized one execution of the new
`radar-interface-acceptance.yml`. It has only `workflow_dispatch`, read-only
repository permissions, one standard Linux job and a sanitized receipt
artifact retained for seven days. The reviewed execution SHA and verified
zero-cost boundary are required inputs. No deployment or cron is enabled.
See `audit/INTERFACE-ACCEPTANCE-2026-10-17.md` for scope and evidence.

The presence of this manual workflow does not authorize later dispatches,
reruns, activation of the original workflows or publication. Those require
their own user approval and unresolved financial/private-access checks.
Do not push an older commit as a branch tip.

The upload-stage restrictions in `audit/PUSH-PREPARATION.md` are historical;
only the specific manual-acceptance exception above has been authorized.

## 2026-10-19 authorized follow-up

The user authorized fixing the manual acceptance branch and one additional
execution **only after current zero-cost conditions are verified**. The manual
workflow now accepts `fix/radar-truthfulness-2026-10-18`, attempt 1 only. Its job
condition requires the cost boolean and matching reviewed/execution SHA before
allocating the runner; shell checks require a full lowercase SHA and verify the
checked-out HEAD before preflight. The default branch remains unchanged.

Current billing access returned HTTP 403 (`Resource not accessible by
integration`); plan, remaining allowance and paid-overage blocking are unverified.
No new dispatch has been issued, and `zero_cost_verified` must remain false.
The 2026-10-17 billing observations and old successful run are historical evidence,
not current cost or data acceptance. See
`audit/workflow-acceptance-2026-10-19/REVIEW.md` for the repair, tests and the
minimum evidence required to proceed. Both publication workflows remain disabled.
