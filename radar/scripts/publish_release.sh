#!/usr/bin/env bash
set -euo pipefail
# The short-lived workflow token is available only in this publishing step.
test "$GITHUB_REPOSITORY" = lwd619783-byte/research-radar
test "$GITHUB_REF" = refs/heads/fix/radar-truthfulness-2026-10-18
test "$GITHUB_RUN_ATTEMPT" = 1
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
current=$(gh api repos/lwd619783-byte/research-radar/git/ref/heads/fix/radar-truthfulness-2026-10-18 --jq .object.sha)
test "$current" = "$GITHUB_SHA" || { echo 'Source advanced; skip obsolete release.'; exit 1; }
gh auth setup-git
publish="$RUNNER_TEMP/radar-publish"
git init -q -b production "$publish"
git -C "$publish" remote add origin https://github.com/lwd619783-byte/research-radar.git
if git ls-remote --exit-code origin refs/heads/production >/dev/null; then
  git -C "$publish" fetch -q --depth=1 origin production
  git -C "$publish" reset -q --hard FETCH_HEAD
fi
cp -R "$RUNNER_TEMP/radar-release/." "$publish/"
git -C "$publish" config user.name 'github-actions[bot]'
git -C "$publish" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$publish" add -- public/index.html public/robots.txt release.json vercel.json verify-release.cjs
git -C "$publish" diff --cached --quiet && exit 0
git -C "$publish" commit -q -m "Publish radar snapshot from $GITHUB_SHA (run $GITHUB_RUN_ID)"
# Ordinary fast-forward only: a concurrent writer causes a failure, never overwrite.
git -C "$publish" push origin HEAD:refs/heads/production
echo "Published source $GITHUB_SHA to production commit $(git -C "$publish" rev-parse HEAD)" >> "$GITHUB_STEP_SUMMARY"
