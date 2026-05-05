#!/usr/bin/env bash
# Advisory contract per shared/conduct/hooks.md — never block, never exit non-zero.
# Cheap pre-filter: if state/buckets.json is absent, no-op silently (opt-in).

set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
STATE_FILE="${PLUGIN_ROOT}/state/buckets.json"

# Opt-in gate: no config file → silent no-op.
if [[ ! -f "$STATE_FILE" ]]; then
  exit 0
fi

# Fail-open: never propagate failure from advisory hook.
python3 "${PLUGIN_ROOT}/scripts/rate-check.py" || true
exit 0
