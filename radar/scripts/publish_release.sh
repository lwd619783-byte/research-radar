#!/usr/bin/env bash
set -euo pipefail
# Scoped token, exact-source guards and ordinary fast-forward are enforced here.
python -B radar/scripts/release_operations.py publish --path "$RUNNER_TEMP/radar-release"
