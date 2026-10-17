# Workflows disabled pending independent audit

Both original workflows are retained byte-for-byte as `*.yml.disabled`.
There are no active `.yml` or `.yaml` workflow files on this branch.
This disables push, pull-request, schedule, and manual workflow triggers
without changing repository or organization settings.

Do not restore the extensions, dispatch workflows, or deploy until the
workflow and private-access protection review has been completed and the
user has explicitly approved activation. Original history is retained for
audit only; do not push an older commit as a branch tip.

GitHub recognizes workflow files ending in `.yml` or `.yaml`:
https://docs.github.com/en/actions/get-started/quickstart

See `audit/PUSH-PREPARATION.md` for the upload-stage status. Existing
handoff deployment instructions are historical and do not authorize action.
