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
