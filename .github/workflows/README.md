# Workflow execution scope

**Current authorization (2026-10-21):** the owner requested automatic market
refresh and Git publication while keeping All Deployments login protection.
`radar-production.yml` implements the new scoped production path described in
`radar/docs/PRODUCTION.md`. The prior manual acceptance workflow and both disabled
legacy publication workflows remain unchanged. The notes below are historical
execution records, not the current automation status.

## Historical manual acceptance scope

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

The initial billing API returned HTTP 403 and that path remains stopped. The
user subsequently supplied current cost screenshots, visually verified by the
parent and independent auditor, and explicitly authorized the one follow-up.
Run 39184829414 executed reviewed SHA
`ee0447a8fc7ede19127917b7f6c28a552ce31a90` on 2026-10-19, attempt 1, and
completed the diagnostic workflow successfully. Runner preflight passed 107
tests and ten frozen hashes. The probe made 119 requests and explicitly reported
`publicationBlocked=true`; workflow success is not data acceptance.

The artifact upload succeeded, but this executor's normal artifact download
received Forbidden and that path was stopped. Original receipt byte verification
and exact blocker review remain pending. Readable original runner logs and the
minimal screenshot evidence summary are archived; no further dispatch or rerun
is authorized. See `audit/workflow-acceptance-2026-10-19/RUN-39184829414.md`.
Both publication workflows remain disabled.
